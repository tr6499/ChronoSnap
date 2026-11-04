from datetime import datetime, timedelta, timezone
import json

from models_usuarios import ConfiguracaoSistema, LogAuditoria
from database import SessionLocal


CHAVE_RETENCAO = "auditoria_retencao_dias"
RETENCAO_PADRAO = 30
FUSO_LOCAL = timezone(timedelta(hours=-3))

ACOES_AUDITORIA = {
    "login": "Entrou no sistema",
    "login_falhou": "Falha ao entrar no sistema",
    "logout": "Saiu do sistema",
    "alterar_senha": "Alterou uma senha",
    "criar": "Cadastrou usuário",
    "atualizar": "Atualizou usuário",
    "excluir": "Excluiu usuário",
    "configurar_banco": "Configurou a conexão do banco de dados",
    "configurar_banco_sqlite": "Selecionou o SQLite como banco de dados",
    "atualizar_retencao_banco": "Alterou a retenção das marcações",
    "compactar_banco": "Compactou o banco de dados",
    "atualizar_layout": "Alterou o layout de exportação RM TOTVS",
    "atualizar_retencao": "Alterou o prazo de retenção da auditoria",
    "limpar": "Removeu registros antigos da auditoria",
    "diagnosticar": "Executou o diagnóstico das marcações",
    "reparar": "Reparou marcações duplicadas",
    "baixou_afd": "Baixou um arquivo AFD",
    "consultou_espelho": "Consultou o espelho de ponto",
    "configurar_atualizacao": "Alterou o modo de atualização do sistema",
}

RECURSOS_AUDITORIA = {
    "autenticacao": "Acesso ao sistema",
    "usuario": "Usuários",
    "banco": "Banco de dados",
    "rm_totvs": "Exportação RM TOTVS",
    "auditoria": "Auditoria",
    "atualizacoes": "Atualizações",
    "marcacoes": "Marcações",
    "espelho_ponto": "Espelho de ponto",
    "afd": "Arquivo AFD",
}


def converter_para_horario_local(data_hora):
    if data_hora is None:
        return None
    if data_hora.tzinfo is None:
        data_hora = data_hora.replace(tzinfo=timezone.utc)
    return data_hora.astimezone(FUSO_LOCAL)


def descrever_acao_auditoria(acao, recurso):
    if acao == "consulta":
        if recurso == "/afd/preview":
            return "Consultou o espelho de ponto"
        return "Consultou informações"
    if acao == "exportacao":
        if recurso.startswith("/afd/download") or recurso == "afd":
            return "Baixou um arquivo AFD"
        return "Baixou um arquivo"
    if acao in ("criar", "atualizar", "excluir"):
        nome_recurso = RECURSOS_AUDITORIA.get(recurso, recurso.replace("_", " "))
        verbo = {"criar": "Cadastrou", "atualizar": "Atualizou", "excluir": "Excluiu"}[acao]
        return f"{verbo} {nome_recurso.lower()}"
    return ACOES_AUDITORIA.get(acao, acao.replace("_", " ").capitalize())


def descrever_recurso_auditoria(recurso):
    if recurso.startswith("/"):
        if recurso.startswith("/afd/download"):
            return "Arquivo AFD"
        if recurso.startswith("/afd/"):
            return "Marcações e espelho de ponto"
        if recurso.startswith("/config/"):
            return "Configurações"
        if recurso.startswith("/system/"):
            return "Sistema e relógios"
        if recurso == "/":
            return "Dashboard"
        return "Sistema"
    return RECURSOS_AUDITORIA.get(recurso, recurso.replace("_", " ").capitalize())


def formatar_detalhes_auditoria(detalhes):
    if not detalhes:
        return []
    try:
        dados = json.loads(detalhes)
    except (TypeError, json.JSONDecodeError):
        return [("Informação", str(detalhes))]
    if not isinstance(dados, dict):
        return [("Informação", str(dados))]

    nomes = {
        "username": "Usuário",
        "usuario_id": "Identificação do usuário",
        "motivo": "Motivo",
        "loja_id": "Identificação da empresa",
        "lojas": "Empresas",
        "data_inicial": "Data inicial",
        "data_final": "Data final",
        "total": "Marcações verificadas",
        "total_funcionarios": "Funcionários encontrados",
        "total_marcacoes": "Marcações encontradas",
        "conflitos": "Possíveis conflitos",
        "dias": "Prazo em dias",
        "removidos": "Registros removidos",
        "valor": "Prazo",
        "unidade": "Unidade",
        "tipo": "Tipo de banco",
        "host": "Servidor do banco",
        "database": "Nome do banco",
        "tamanho_antes": "Tamanho antes (bytes)",
        "tamanho_depois": "Tamanho depois (bytes)",
        "espaco_liberado": "Espaço liberado (bytes)",
        "status_code": "Resultado técnico",
        "status": "Resultado",
        "remember_me": "Manter sessão",
        "modo": "Modo",
        "empresa": "Empresa",
        "arquivos": "Arquivos gerados",
        "formato": "Formato",
    }
    return [
        (
            nomes.get(chave, chave.replace("_", " ").capitalize()),
            json.dumps(valor, ensure_ascii=False) if isinstance(valor, (dict, list)) else str(valor),
        )
        for chave, valor in dados.items()
        if chave != "metodo"
    ]


def obter_retencao_dias(db=None):
    propria_sessao = db is None
    sessao = db or SessionLocal()
    try:
        configuracao = sessao.query(ConfiguracaoSistema).filter(
            ConfiguracaoSistema.chave == CHAVE_RETENCAO
        ).first()
        try:
            dias = int(configuracao.valor) if configuracao else RETENCAO_PADRAO
        except (TypeError, ValueError):
            dias = RETENCAO_PADRAO
        return max(1, dias)
    finally:
        if propria_sessao:
            sessao.close()


def garantir_configuracao_retencao(db):
    configuracao = db.query(ConfiguracaoSistema).filter(
        ConfiguracaoSistema.chave == CHAVE_RETENCAO
    ).first()
    if not configuracao:
        db.add(ConfiguracaoSistema(
            chave=CHAVE_RETENCAO,
            valor=str(RETENCAO_PADRAO),
            descricao="Quantidade de dias para manter os logs de auditoria."
        ))
        db.commit()


def limpar_logs_auditoria(db=None):
    propria_sessao = db is None
    sessao = db or SessionLocal()
    try:
        dias = obter_retencao_dias(sessao)
        limite = datetime.utcnow() - timedelta(days=dias)
        removidos = sessao.query(LogAuditoria).filter(
            LogAuditoria.criado_em < limite
        ).delete(synchronize_session=False)
        sessao.commit()
        return removidos
    finally:
        if propria_sessao:
            sessao.close()


def registrar_auditoria(
    acao,
    recurso,
    usuario=None,
    detalhes=None,
    sucesso=True,
    status_code=None,
    db=None
):
    propria_sessao = db is None
    sessao = db or SessionLocal()
    try:
        evento = LogAuditoria(
            usuario_id=getattr(usuario, "id", None),
            username=getattr(usuario, "username", None) or "sistema",
            acao=acao,
            recurso=recurso,
            detalhes=json.dumps(detalhes, ensure_ascii=False) if detalhes else None,
            sucesso=sucesso,
            status_code=status_code
        )
        sessao.add(evento)
        sessao.commit()
        return evento
    except Exception:
        sessao.rollback()
        return None
    finally:
        if propria_sessao:
            sessao.close()


def registrar_auditoria_request(request, acao, recurso, usuario=None, detalhes=None, sucesso=True, status_code=None):
    if usuario is None:
        sessao = getattr(request, "cookies", {}).get("chronosnap_session")
        if sessao:
            from services.autenticacao import sessao_manager
            dados = sessao_manager.validar_sessao(sessao)
            if dados:
                usuario = type("UsuarioAuditoria", (), {
                    "id": dados.get("usuario_id"),
                    "username": dados.get("username")
                })()
    return registrar_auditoria(
        acao=acao,
        recurso=recurso,
        usuario=usuario,
        detalhes=detalhes,
        sucesso=sucesso,
        status_code=status_code
    )
