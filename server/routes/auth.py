from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import SessionLocal
from models_usuarios import UsuarioSistema
from services.autenticacao import (
    hash_password, verify_password, sessao_manager, config_auth, UsuarioAutenticado
)
from services.auditoria import registrar_auditoria

router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class MudarSenhaRequest(BaseModel):
    senha_atual: str
    senha_nova: str
    senha_nova_confirmacao: str


@router.get("/login")
async def login_page(request: Request):
    """Página de login - splash screen"""
    
    # Verificar se está em modo admin livre
    if config_auth.admin_mode_livre:
        return RedirectResponse(url="/", status_code=303)
    
    # Verificar se tem cookie de sessão
    token = request.cookies.get("chronosnap_session")
    if token and sessao_manager.validar_sessao(token):
        return RedirectResponse(url="/", status_code=303)
    
    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )


@router.post("/login")
async def fazer_login(request: LoginRequest, response: Response):
    """Autentica o usuário"""
    
    db = SessionLocal()
    
    try:
        # Procurar usuário no banco
        usuario = db.query(UsuarioSistema).filter(
            UsuarioSistema.username == request.username
        ).first()
        
        if not usuario or not usuario.ativo:
            registrar_auditoria(
                acao="login_falhou",
                recurso="autenticacao",
                detalhes={"username": request.username},
                sucesso=False,
                status_code=401
            )
            raise HTTPException(
                status_code=401,
                detail="Usuário não encontrado ou inativo"
            )
        
        # Verificar senha
        if not verify_password(request.password, usuario.password_hash):
            registrar_auditoria(
                acao="login_falhou",
                recurso="autenticacao",
                usuario=usuario,
                detalhes={"motivo": "credenciais_invalidas"},
                sucesso=False,
                status_code=401
            )
            raise HTTPException(
                status_code=401,
                detail="Usuário ou senha incorretos"
            )
        
        # Criar sessão
        token = sessao_manager.criar_sessao(
            usuario_id=usuario.id,
            username=usuario.username,
            nome=usuario.nome,
            perfil=usuario.perfil,
            duracao_minutos=480 if request.remember_me else 120
        )
        
        # Definir cookie da sessão
        response.set_cookie(
            key="chronosnap_session",
            value=token,
            httponly=True,
            secure=False,  # Mude para True em produção com HTTPS
            samesite="Lax",
            max_age=None if not request.remember_me else 480 * 60  # 480 minutos em segundos
        )

        registrar_auditoria(
            acao="login",
            recurso="autenticacao",
            usuario=usuario,
            detalhes={"remember_me": request.remember_me}
        )
        
        return {
            "token": token,
            "usuario": {
                "id": usuario.id,
                "username": usuario.username,
                "nome": usuario.nome,
                "perfil": usuario.perfil
            }
        }
    
    finally:
        db.close()


@router.get("/logout")
async def fazer_logout(request: Request):
    """Faz logout do usuário"""
    
    token = request.cookies.get("chronosnap_session")
    usuario = None
    if token:
        dados_sessao = sessao_manager.validar_sessao(token)
        if dados_sessao:
            usuario = type("UsuarioAuditoria", (), {
                "id": dados_sessao.get("usuario_id"),
                "username": dados_sessao.get("username")
            })()
    registrar_auditoria(
        acao="logout",
        recurso="autenticacao",
        usuario=usuario
    )
    if token:
        sessao_manager.remover_sessao(token)
    
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie("chronosnap_session")
    return response


@router.post("/mudar-senha/{usuario_id}")
async def mudar_senha(usuario_id: int, dados: MudarSenhaRequest):
    """Muda a senha de um usuário"""
    
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
        
        # Procurar usuário
        usuario = db.query(UsuarioSistema).filter(
            UsuarioSistema.id == usuario_id
        ).first()
        
        if not usuario:
            raise HTTPException(
                status_code=404,
                detail="Usuário não encontrado"
            )
        
        # Verificar senha atual
        if not verify_password(dados.senha_atual, usuario.password_hash):
            raise HTTPException(
                status_code=401,
                detail="Senha atual incorreta"
            )
        
        # Atualizar senha
        usuario.password_hash = hash_password(dados.senha_nova)
        db.commit()

        registrar_auditoria(
            acao="alterar_senha",
            recurso="usuario",
            usuario=obter_usuario_da_sessao(request),
            detalhes={"usuario_id": usuario.id}
        )
        
        return {
            "mensagem": "Senha alterada com sucesso"
        }
    
    finally:
        db.close()


def obter_usuario_da_sessao(request: Request) -> UsuarioAutenticado:
    """Obtém o usuário autenticado da sessão"""
    
    # Verificar modo admin livre
    if config_auth.admin_mode_livre:
        return UsuarioAutenticado(
            id=1,
            username="admin",
            nome="Administrador",
            perfil="Completo"
        )
    
    # Procurar token na cookie
    token = request.cookies.get("chronosnap_session")
    
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Não autenticado"
        )
    
    # Validar sessão
    sessao = sessao_manager.validar_sessao(token)
    
    if not sessao:
        raise HTTPException(
            status_code=401,
            detail="Sessão expirada"
        )
    
    return UsuarioAutenticado(
        id=sessao["usuario_id"],
        username=sessao["username"],
        nome=sessao["nome"],
        perfil=sessao["perfil"]
    )
