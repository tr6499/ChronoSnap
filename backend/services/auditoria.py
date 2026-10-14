from datetime import datetime, timedelta
import json

from models_usuarios import ConfiguracaoSistema, LogAuditoria
from database import SessionLocal


CHAVE_RETENCAO = "auditoria_retencao_dias"
RETENCAO_PADRAO = 30


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
