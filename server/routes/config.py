from pathlib import Path
import json
from sqlalchemy import inspect
from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import (
    DATABASE_CONFIG,
    SessionLocal,
    carregar_configuracao_banco,
    normalizar_configuracao,
    salvar_configuracao_banco,
)
from models_usuarios import UsuarioSistema, ConfiguracaoSistema, LogAuditoria
from routes.auth import obter_usuario_da_sessao
from services.autenticacao import hash_password, verify_password, config_auth
from services.auditoria import obter_retencao_dias, limpar_logs_auditoria, registrar_auditoria, CHAVE_RETENCAO
from models import MarcacaoAFD
from models import Loja
from services.retencao_banco import (
    UNIDADES, obter_retencao_banco, salvar_retencao_banco,
    aplicar_retencao_banco, compactar_banco
)
from services.banco_dados import (
    conexoes_sugeridas,
    configuracao_publica,
    criar_tabelas,
    detectar_postgresql_local,
    informacoes_servidor,
    migrar_sqlite,
    nome_provedor,
    provedores_disponiveis,
    provisionar_banco,
    testar_conexao,
)
from services.marcacoes import diagnosticar_marcacoes, reparar_duplicidades
from database import BANCO_DIR, PROVEDORES, SQLITE_DATABASE_FILE, engine

router = APIRouter(
    prefix="/config",
    tags=["Config"]
)

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

ADMIN_USERNAME = "admin"


def exigir_administrador(request):
    usuario = obter_usuario_da_sessao(request)
    if not usuario.tem_permissao_configuracoes():
        raise HTTPException(status_code=403, detail="Permissão negada")
    return usuario


CHAVE_LAYOUT_RM = "layout_rm_totvs"
LAYOUT_RM_PADRAO = {
    "nsr_largura": 10,
    "data_formato": "%d%m%Y",
    "hora_formato": "%H%M",
    "identificador_largura": 12,
    "preenchimento": "0",
    "separador": ""
}


def obter_layout_rm(db):
    configuracao = db.query(ConfiguracaoSistema).filter(
        ConfiguracaoSistema.chave == CHAVE_LAYOUT_RM
    ).first()
    if not configuracao:
        return dict(LAYOUT_RM_PADRAO)
    try:
        layout = json.loads(configuracao.valor or "{}")
    except json.JSONDecodeError:
        layout = {}
    return {**LAYOUT_RM_PADRAO, **layout}


def usuario_administrador_protegido(usuario: UsuarioSistema) -> bool:
    return usuario.username.strip().lower() == ADMIN_USERNAME


def erro_integridade_administrador() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=(
            "Violação de integridade do sistema: o usuário Administrador "
            "não pode ser editado, desativado ou excluído."
        )
    )


class MudarSenhaAdminRequest(BaseModel):
    senha_atual: str
    senha_nova: str
    senha_nova_confirmacao: str


class UsuarioRequest(BaseModel):
    username: str
    nome: str
    email: str | None = None
    perfil: str = "Restrito"
    ativo: bool = True
    senha: str | None = None


@router.get("/usuarios")
async def usuarios_page(request: Request):
    """Página de gerenciamento de usuários"""
    
    try:
        usuario = obter_usuario_da_sessao(request)
        
        if not usuario.tem_permissao_usuarios():
            raise HTTPException(
                status_code=403,
                detail="Permissão negada"
            )
    except HTTPException:
        # Se não autenticado, redireciona para login
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/auth/login", status_code=303)
    
    db = SessionLocal()
    
    try:
        usuarios = db.query(UsuarioSistema).order_by(UsuarioSistema.username).all()
        
        return templates.TemplateResponse(
            request=request,
            name="usuarios.html",
            context={
                "usuarios": usuarios
            }
        )
    
    finally:
        db.close()


@router.get("/usuarios/list")
async def listar_usuarios(request: Request):
    """API para listar usuários"""
    
    try:
        usuario = obter_usuario_da_sessao(request)
        
        if not usuario.tem_permissao_usuarios():
            raise HTTPException(
                status_code=403,
                detail="Permissão negada"
            )
    except HTTPException:
        raise HTTPException(
            status_code=401,
            detail="Não autenticado"
        )
    
    db = SessionLocal()
    
    try:
        usuarios = db.query(UsuarioSistema).order_by(UsuarioSistema.username).all()
        
        return [
            {
                "id": u.id,
                "username": u.username,
                "nome": u.nome,
                "email": u.email,
                "perfil": u.perfil,
                "ativo": u.ativo
            }
            for u in usuarios
        ]
    
    finally:
        db.close()


@router.post("/usuarios")
async def criar_usuario(request: Request, dados: UsuarioRequest):

    usuario_atual = obter_usuario_da_sessao(request)

    if not usuario_atual.tem_permissao_usuarios():
        raise HTTPException(status_code=403, detail="Permissão negada")

    username = dados.username.strip().lower()
    nome = dados.nome.strip()

    if not username or not nome:
        raise HTTPException(
            status_code=400,
            detail="Usuário e nome são obrigatórios."
        )

    if dados.perfil not in ("Completo", "Restrito"):
        raise HTTPException(status_code=400, detail="Perfil inválido.")

    if not dados.senha or len(dados.senha) < 6:
        raise HTTPException(
            status_code=400,
            detail="A senha deve ter pelo menos 6 caracteres."
        )

    db = SessionLocal()

    try:

        if db.query(UsuarioSistema).filter(
            UsuarioSistema.username == username
        ).first():
            raise HTTPException(
                status_code=409,
                detail="Este usuário já está cadastrado."
            )

        usuario = UsuarioSistema(
            username=username,
            nome=nome,
            email=(dados.email or "").strip() or None,
            perfil=dados.perfil,
            ativo=dados.ativo,
            password_hash=hash_password(dados.senha)
        )

        db.add(usuario)
        db.commit()
        db.refresh(usuario)

        registrar_auditoria(
            acao="criar",
            recurso="usuario",
            usuario=usuario_atual,
            detalhes={"usuario_id": usuario.id, "username": usuario.username}
        )

        return {"id": usuario.id, "mensagem": "Usuário criado."}

    finally:
        db.close()


@router.put("/usuarios/{usuario_id}")
async def atualizar_usuario(
    usuario_id: int,
    request: Request,
    dados: UsuarioRequest
):

    usuario_atual = obter_usuario_da_sessao(request)

    if not usuario_atual.tem_permissao_usuarios():
        raise HTTPException(status_code=403, detail="Permissão negada")

    username = dados.username.strip().lower()
    nome = dados.nome.strip()

    if not username or not nome:
        raise HTTPException(
            status_code=400,
            detail="Usuário e nome são obrigatórios."
        )

    if dados.perfil not in ("Completo", "Restrito"):
        raise HTTPException(status_code=400, detail="Perfil inválido.")

    if dados.senha and len(dados.senha) < 6:
        raise HTTPException(
            status_code=400,
            detail="A senha deve ter pelo menos 6 caracteres."
        )

    db = SessionLocal()

    try:

        usuario = db.query(UsuarioSistema).filter(
            UsuarioSistema.id == usuario_id
        ).first()

        if not usuario:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")

        if usuario_administrador_protegido(usuario):
            raise erro_integridade_administrador()

        existente = db.query(UsuarioSistema).filter(
            UsuarioSistema.username == username,
            UsuarioSistema.id != usuario_id
        ).first()

        if existente:
            raise HTTPException(
                status_code=409,
                detail="Este usuário já está cadastrado."
            )

        if usuario.id == usuario_atual.id and not dados.ativo:
            raise HTTPException(
                status_code=400,
                detail="Não é possível desativar seu próprio usuário."
            )

        usuario.username = username
        usuario.nome = nome
        usuario.email = (dados.email or "").strip() or None
        usuario.perfil = dados.perfil
        usuario.ativo = dados.ativo

        if dados.senha:
            usuario.password_hash = hash_password(dados.senha)

        db.commit()

        registrar_auditoria(
            acao="atualizar",
            recurso="usuario",
            usuario=usuario_atual,
            detalhes={"usuario_id": usuario.id, "username": usuario.username}
        )

        return {"mensagem": "Usuário atualizado."}

    finally:
        db.close()


@router.delete("/usuarios/{usuario_id}")
async def excluir_usuario(usuario_id: int, request: Request):

    usuario_atual = obter_usuario_da_sessao(request)

    if not usuario_atual.tem_permissao_usuarios():
        raise HTTPException(status_code=403, detail="Permissão negada")

    db = SessionLocal()

    try:

        usuario = db.query(UsuarioSistema).filter(
            UsuarioSistema.id == usuario_id
        ).first()

        if not usuario:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")

        if usuario_administrador_protegido(usuario):
            raise erro_integridade_administrador()

        if usuario_id == usuario_atual.id:
            raise HTTPException(
                status_code=400,
                detail="Não é possível excluir seu próprio usuário."
            )

        db.delete(usuario)
        db.commit()

        registrar_auditoria(
            acao="excluir",
            recurso="usuario",
            usuario=usuario_atual,
            detalhes={"usuario_id": usuario_id, "username": usuario.username}
        )

        return {"mensagem": "Usuário excluído."}

    finally:
        db.close()


@router.get("/senha-admin")
async def senha_admin_page(request: Request):
    """Página para mudar senha do admin"""
    
    try:
        usuario = obter_usuario_da_sessao(request)
        
        if not usuario.tem_permissao_configuracoes():
            raise HTTPException(
                status_code=403,
                detail="Permissão negada"
            )
    except HTTPException:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/auth/login", status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="senha-admin.html",
        context={}
    )


@router.post("/senha-admin")
async def atualizar_senha_admin(request: Request, dados: MudarSenhaAdminRequest):
    """Atualiza a senha do admin"""
    
    try:
        usuario = obter_usuario_da_sessao(request)
        
        if not usuario.tem_permissao_configuracoes():
            raise HTTPException(
                status_code=403,
                detail="Permissão negada"
            )
    except HTTPException as e:
        if e.status_code == 403:
            raise
        raise HTTPException(status_code=401, detail="Não autenticado")
    
    db = SessionLocal()
    
    try:
        # Validar dados
        if dados.senha_nova != dados.senha_nova_confirmacao:
            raise HTTPException(
                status_code=400,
                detail="As senhas não coincidem"
            )
        
        if len(dados.senha_nova) < 6:
            raise HTTPException(
                status_code=400,
                detail="A senha deve ter pelo menos 6 caracteres"
            )
        
        # Procurar usuário admin
        admin = db.query(UsuarioSistema).filter(
            UsuarioSistema.username == "admin"
        ).first()
        
        if not admin:
            raise HTTPException(
                status_code=404,
                detail="Usuário admin não encontrado"
            )
        
        # Verificar senha atual
        if not verify_password(dados.senha_atual, admin.password_hash):
            raise HTTPException(
                status_code=401,
                detail="Senha atual incorreta"
            )
        
        # Atualizar senha
        admin.password_hash = hash_password(dados.senha_nova)
        db.commit()
        
        return {
            "mensagem": "Senha do admin alterada com sucesso"
        }
    
    finally:
        db.close()


@router.get("/modo-admin")
async def modo_admin_page(request: Request):
    """Página de configuração do modo admin"""
    
    try:
        usuario = obter_usuario_da_sessao(request)
        
        if not usuario.tem_permissao_configuracoes():
            raise HTTPException(
                status_code=403,
                detail="Permissão negada"
            )
    except HTTPException:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/auth/login", status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="modo-admin.html",
        context={
            "admin_mode_livre": config_auth.admin_mode_livre
        }
    )


@router.post("/modo-admin")
async def atualizar_modo_admin(request: Request, data: dict):
    """Ativa/desativa o modo admin sem login"""
    
    try:
        usuario = obter_usuario_da_sessao(request)
        
        if not usuario.tem_permissao_configuracoes():
            raise HTTPException(
                status_code=403,
                detail="Permissão negada"
            )
    except HTTPException as e:
        if e.status_code == 403:
            raise
        raise HTTPException(status_code=401, detail="Não autenticado")
    
    enable = data.get("enable", False)
    
    if enable:
        config_auth.ativar_modo_admin_livre()
        mensagem = "Modo admin ativado com sucesso"
    else:
        config_auth.desativar_modo_admin_livre()
        mensagem = "Modo admin desativado com sucesso"
    
    return {
        "mensagem": mensagem,
        "admin_mode": enable
    }


@router.get("/auditoria")
async def auditoria_page(request: Request):
    exigir_administrador(request)
    db = SessionLocal()
    try:
        logs = db.query(LogAuditoria).order_by(
            LogAuditoria.criado_em.desc()
        ).limit(500).all()
        return templates.TemplateResponse(
            request=request,
            name="auditoria.html",
            context={
                "logs": logs,
                "retencao_dias": obter_retencao_dias(db)
            }
        )
    finally:
        db.close()


@router.get("/banco")
async def banco_page(request: Request):
    exigir_administrador(request)
    db = SessionLocal()
    try:
        tabelas = inspect(engine).get_table_names()
        banco_atual = configuracao_publica()
        arquivo = SQLITE_DATABASE_FILE
        lojas = db.query(Loja).order_by(Loja.numero).all()
        retencao = obter_retencao_banco(db)
        return templates.TemplateResponse(
            request=request,
            name="banco.html",
            context={
                "banco_atual": banco_atual,
                "banco_sqlite": DATABASE_CONFIG["backend"] == "sqlite",
                "banco_caminho": banco_atual["local"],
                "banco_tamanho": (
                    arquivo.stat().st_size
                    if DATABASE_CONFIG["backend"] == "sqlite" and arquivo.exists()
                    else None
                ),
                "tabelas": tabelas,
                "marcacoes_total": db.query(MarcacaoAFD).count(),
                "lojas": lojas,
                "retencao_valor": retencao[0],
                "retencao_unidade": retencao[1],
                "provedores": provedores_disponiveis(),
                "conexoes": conexoes_sugeridas(),
                "banco_destino_backend": carregar_configuracao_banco()["backend"],
                "arquivo_sqlite_existe": arquivo.is_file(),
                "servidor": informacoes_servidor(),
                "postgresql_local": detectar_postgresql_local(),
            }
        )
    finally:
        db.close()


def _mesmo_servidor(host_a, host_b):
    locais = {"localhost", "127.0.0.1", "::1"}
    a, b = str(host_a).strip().lower(), str(host_b).strip().lower()
    return a == b or (a in locais and b in locais)


def _configuracao_recebida(dados):
    backend = dados.get("backend", "postgresql")
    configuracao = {
        "backend": backend,
        "host": dados.get("host", ""),
        "port": dados.get("port", 0),
        "database": dados.get("database", ""),
        "username": dados.get("username", ""),
        "password": dados.get("password", ""),
    }
    atual = carregar_configuracao_banco()
    if (
        not configuracao["password"]
        and atual["backend"] == backend
        and _mesmo_servidor(configuracao["host"], atual["host"])
        and all(
            configuracao[chave] == atual[chave]
            for chave in ("port", "database", "username")
        )
    ):
        configuracao["password"] = atual["password"]
    return configuracao


def _validar_provedor_recebido(configuracao):
    if configuracao["backend"] == "sqlite":
        raise HTTPException(status_code=400, detail="Provedor inválido.")
    try:
        nome_provedor(configuracao["backend"])
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Provedor inválido.") from exc


@router.post("/banco/conexao/testar")
def testar_conexao_banco(request: Request, dados: dict):
    exigir_administrador(request)
    configuracao = _configuracao_recebida(dados)
    _validar_provedor_recebido(configuracao)
    try:
        testar_conexao(configuracao)
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "mensagem": (
            f"Conexão com {nome_provedor(configuracao['backend'])} "
            "estabelecida com sucesso."
        )
    }


@router.post("/banco/conexao/configurar")
def configurar_conexao_banco(request: Request, dados: dict):
    usuario = exigir_administrador(request)
    configuracao = _configuracao_recebida(dados)
    _validar_provedor_recebido(configuracao)
    nome = nome_provedor(configuracao["backend"])
    try:
        testar_conexao(configuracao)
        criar_tabelas(configuracao)
        configuracao = salvar_configuracao_banco(configuracao)
    except (ValueError, ConnectionError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _auditar_banco(
        usuario,
        "configurar_banco",
        {
            "tipo": nome,
            "host": configuracao["host"],
            "database": configuracao["database"],
        },
    )
    return {
        "mensagem": (
            f"{nome} configurado e tabelas criadas. Reinicie o servidor "
            "pelo Manager para aplicar a alteração. Os dados atuais não "
            "foram copiados."
        )
    }


def _auditar_banco(usuario, acao, detalhes):
    db = SessionLocal()
    try:
        registrar_auditoria(
            acao=acao,
            recurso="banco",
            usuario=usuario,
            detalhes=detalhes,
            db=db,
        )
    finally:
        db.close()


@router.post("/banco/sqlite/configurar")
async def configurar_sqlite(request: Request):
    usuario = exigir_administrador(request)
    try:
        salvar_configuracao_banco({"backend": "sqlite"})
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    db = SessionLocal()
    try:
        registrar_auditoria(
            acao="configurar_banco_sqlite",
            recurso="banco",
            usuario=usuario,
            detalhes={},
            db=db,
        )
    finally:
        db.close()
    return {
        "mensagem": (
            "SQLite selecionado. Reinicie o servidor pelo Manager "
            "para aplicar a alteração."
        )
    }


def _migrar_e_salvar(usuario, configuracao):
    nome = nome_provedor(configuracao["backend"])
    try:
        testar_conexao(configuracao)
        migrar_sqlite(configuracao)
    except (ValueError, ConnectionError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        configuracao = salvar_configuracao_banco(configuracao)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Os dados foram copiados para o {nome}, mas não foi "
                "possível salvar a configuração. Use “Aplicar” sem a opção "
                "de copiar os dados."
            ),
        ) from exc
    _auditar_banco(
        usuario,
        "migrar_sqlite_banco",
        {
            "tipo": nome,
            "host": configuracao["host"],
            "database": configuracao["database"],
        },
    )
    return configuracao


def _mensagem_migracao(backend):
    return (
        "Migração concluída. O SQLite original foi preservado. "
        f"Reinicie o servidor pelo Manager para passar a usar o {nome_provedor(backend)}."
    )


@router.post("/banco/conexao/migrar")
def migrar_para_banco(request: Request, dados: dict):
    usuario = exigir_administrador(request)
    configuracao = _configuracao_recebida(dados)
    _validar_provedor_recebido(configuracao)
    _migrar_e_salvar(usuario, configuracao)
    return {"mensagem": _mensagem_migracao(configuracao["backend"])}


@router.post("/banco/conexao/criar")
def criar_banco_conexao(request: Request, dados: dict):
    usuario = exigir_administrador(request)
    configuracao = _configuracao_recebida(dados)
    _validar_provedor_recebido(configuracao)
    backend = configuracao["backend"]
    nome = nome_provedor(backend)
    administrador = dados.get("administrador")
    if not isinstance(administrador, dict) or not administrador.get("username"):
        raise HTTPException(
            status_code=400,
            detail=f"Informe o usuário administrador do {nome}.",
        )
    if not configuracao["password"]:
        raise HTTPException(
            status_code=400,
            detail="Defina a senha do novo usuário do banco.",
        )
    try:
        configuracao = normalizar_configuracao(configuracao)
        provisionar_banco(
            {
                "host": configuracao["host"],
                "port": configuracao["port"],
                "username": str(administrador.get("username", "")).strip(),
                "password": str(administrador.get("password", "")),
            },
            configuracao,
        )
    except (ValueError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _auditar_banco(
        usuario,
        "criar_banco",
        {
            "tipo": nome,
            "host": configuracao["host"],
            "database": configuracao["database"],
            "usuario": configuracao["username"],
        },
    )

    if dados.get("migrar") and PROVEDORES[backend].get("migracao"):
        try:
            _migrar_e_salvar(usuario, configuracao)
        except HTTPException as exc:
            exc.detail = (
                "Usuário e banco foram criados, mas a migração não foi "
                f"concluída. {exc.detail} Corrija o problema e use "
                "“Usar um banco que já existe”."
            )
            raise
        return {"mensagem": _mensagem_migracao(backend)}

    try:
        criar_tabelas(configuracao)
        salvar_configuracao_banco(configuracao)
    except (ValueError, ConnectionError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "mensagem": (
            "Usuário, banco e tabelas criados. Reinicie o servidor pelo "
            "Manager para aplicar a alteração. Os dados atuais não foram "
            "copiados."
        )
    }


@router.post("/banco/retencao")
async def salvar_retencao(request: Request, dados: dict):
    usuario = exigir_administrador(request)
    unidade = dados.get("unidade")
    try:
        valor = int(dados.get("valor", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Informe um número válido.")
    if unidade not in UNIDADES:
        raise HTTPException(status_code=400, detail="Unidade inválida.")
    if valor < 0 or valor > 3650:
        raise HTTPException(status_code=400, detail="O período deve ficar entre 0 e 3650.")

    db = SessionLocal()
    try:
        salvar_retencao_banco(db, valor, unidade)
        removidos = aplicar_retencao_banco(db)
        registrar_auditoria(
            acao="atualizar_retencao_banco",
            recurso="banco",
            usuario=usuario,
            detalhes={"valor": valor, "unidade": unidade, "removidos": removidos},
            db=db
        )
        return {
            "mensagem": "Retenção desativada." if valor == 0 else "Retenção atualizada.",
            "removidos": removidos
        }
    finally:
        db.close()


@router.post("/banco/compactar")
def compactar_banco_endpoint(request: Request):
    usuario = exigir_administrador(request)
    if engine.dialect.name != "sqlite":
        raise HTTPException(
            status_code=409,
            detail="A compactação de arquivo está disponível somente no SQLite.",
        )
    arquivo = BANCO_DIR / "afd.db"
    tamanho_antes = arquivo.stat().st_size if arquivo.exists() else 0
    compactar_banco()
    tamanho_depois = arquivo.stat().st_size if arquivo.exists() else 0
    espaco_liberado = max(tamanho_antes - tamanho_depois, 0)

    db = SessionLocal()
    try:
        registrar_auditoria(
            acao="compactar_banco",
            recurso="banco",
            usuario=usuario,
            detalhes={
                "tamanho_antes": tamanho_antes,
                "tamanho_depois": tamanho_depois,
                "espaco_liberado": espaco_liberado
            },
            db=db
        )
    finally:
        db.close()

    return {
        "mensagem": "Compactação concluída.",
        "tamanho_antes": tamanho_antes,
        "tamanho_depois": tamanho_depois,
        "espaco_liberado": espaco_liberado
    }


@router.get("/layout-rm")
async def layout_rm_page(request: Request):
    exigir_administrador(request)
    db = SessionLocal()
    try:
        return templates.TemplateResponse(
            request=request,
            name="layout-rm.html",
            context={"layout": obter_layout_rm(db)}
        )
    finally:
        db.close()


@router.post("/layout-rm")
async def salvar_layout_rm(request: Request, dados: dict):
    usuario = exigir_administrador(request)
    try:
        layout = {
            "nsr_largura": max(1, min(30, int(dados.get("nsr_largura", 10)))),
            "data_formato": str(dados.get("data_formato", "%d%m%Y"))[:30],
            "hora_formato": str(dados.get("hora_formato", "%H%M"))[:30],
            "identificador_largura": max(1, min(30, int(dados.get("identificador_largura", 12)))),
            "preenchimento": (str(dados.get("preenchimento", "0")) or "0")[0],
            "separador": str(dados.get("separador", ""))[:5]
        }
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Valores inválidos no layout.")
    db = SessionLocal()
    try:
        configuracao = db.query(ConfiguracaoSistema).filter(
            ConfiguracaoSistema.chave == CHAVE_LAYOUT_RM
        ).first()
        if not configuracao:
            configuracao = ConfiguracaoSistema(chave=CHAVE_LAYOUT_RM)
            db.add(configuracao)
        configuracao.valor = json.dumps(layout, ensure_ascii=False)
        configuracao.descricao = "Layout configurável da exportação RM TOTVS."
        db.commit()
        registrar_auditoria("atualizar_layout", "rm_totvs", usuario, layout, db=db)
        return {"success": True, "layout": layout}
    finally:
        db.close()


@router.post("/auditoria/configuracao")
async def atualizar_auditoria_configuracao(request: Request, dados: dict):
    usuario = exigir_administrador(request)
    try:
        dias = int(dados.get("dias", 30))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Informe um número válido de dias.")
    if dias < 1 or dias > 3650:
        raise HTTPException(status_code=400, detail="A retenção deve ficar entre 1 e 3650 dias.")

    db = SessionLocal()
    try:
        configuracao = db.query(ConfiguracaoSistema).filter(
            ConfiguracaoSistema.chave == CHAVE_RETENCAO
        ).first()
        configuracao.valor = str(dias)
        db.commit()
        removidos = limpar_logs_auditoria(db)
        registrar_auditoria(
            acao="atualizar_retencao",
            recurso="auditoria",
            usuario=usuario,
            detalhes={"dias": dias, "removidos": removidos},
            db=db
        )
        return {"mensagem": "Retenção atualizada.", "dias": dias}
    finally:
        db.close()


@router.post("/auditoria/limpar")
async def limpar_auditoria(request: Request):
    usuario = exigir_administrador(request)
    db = SessionLocal()
    try:
        removidos = limpar_logs_auditoria(db)
        registrar_auditoria(
            acao="limpar",
            recurso="auditoria",
            usuario=usuario,
            detalhes={"removidos": removidos},
            db=db
        )
        return {"mensagem": f"{removidos} log(s) removido(s).", "removidos": removidos}
    finally:
        db.close()


@router.get("/marcacoes/diagnostico")
async def diagnostico_marcacoes(request: Request, loja_id: int | None = None):
    usuario = exigir_administrador(request)
    db = SessionLocal()
    try:
        resultado = diagnosticar_marcacoes(db, loja_id)
        registrar_auditoria(
            acao="diagnosticar",
            recurso="marcacoes",
            usuario=usuario,
            detalhes={"loja_id": loja_id, "total": resultado["total"], "conflitos": resultado["possiveis_reinicios_nsr"]},
            db=db
        )
        return resultado
    finally:
        db.close()


@router.post("/marcacoes/reparar")
async def reparar_marcacoes(request: Request, dados: dict):
    usuario = exigir_administrador(request)
    if dados.get("confirmar") is not True:
        raise HTTPException(status_code=400, detail="Envie confirmar=true para executar o reparo.")
    db = SessionLocal()
    try:
        resultado = reparar_duplicidades(db, dados.get("loja_id"), confirmar=True)
        registrar_auditoria(
            acao="reparar",
            recurso="marcacoes",
            usuario=usuario,
            detalhes={"loja_id": dados.get("loja_id"), **resultado},
            db=db
        )
        return resultado
    finally:
        db.close()
