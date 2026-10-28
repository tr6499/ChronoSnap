from pathlib import Path
import asyncio
from contextlib import asynccontextmanager
from sqlalchemy import inspect, text

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from database import Base, engine, SessionLocal
import models
from models_usuarios import UsuarioSistema, ConfiguracaoSistema
from services.auditoria import garantir_configuracao_retencao, limpar_logs_auditoria

from routes.afd import router as afd_router, executar_agendador_automacoes, _carregar_automacoes
from routes.users import router as users_router
from routes.company import router as company_router
from routes.system import router as system_router
from routes.lojas import router as lojas_router
from routes.dashboard import router as dashboard_router
from routes.funcionarios import router as funcionarios_router
from routes.auth import router as auth_router
from routes.config import router as config_router
from routes.licenca import router as licenca_router
from services.monitor import monitorar_lojas
from services.retencao_banco import executar_retencao_banco
from services.autenticacao import (
    hash_password,
    sessao_manager,
    config_auth
)
from services.auditoria import registrar_auditoria_request


# ============================================================
# CONFIGURAÇÃO
# ============================================================

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app):
    _carregar_automacoes()
    tarefas = [
        asyncio.create_task(monitorar_lojas()),
        asyncio.create_task(executar_agendador_automacoes()),
        asyncio.create_task(executar_retencao_banco()),
    ]

    try:
        yield
    finally:
        for tarefa in tarefas:
            tarefa.cancel()
        for tarefa in tarefas:
            try:
                await tarefa
            except asyncio.CancelledError:
                pass

app = FastAPI(
    title="ChronoSnap",
    version="1.0.3",
    lifespan=lifespan
)


# ============================================================
# MIDDLEWARE DE AUTENTICAÇÃO
# ============================================================

class AutenticacaoMiddleware(BaseHTTPMiddleware):
    """
    Middleware que verifica autenticação em todas as rotas.
    Rotas públicas: /auth/*, /static/*, /docs, /openapi.json, /redoc
    """
    
    # Rotas que não requerem autenticação
    ROTAS_PUBLICAS = [
        "/auth/",
        "/static/",
        "/docs",
        "/openapi.json",
        "/redoc",
    ]

    @staticmethod
    def registrar_evento_requisicao(request, resposta):
        caminho = request.url.path

        if caminho.startswith(("/static/", "/docs", "/redoc", "/openapi.json")):
            return

        if caminho == "/api/dashboard/status":
            return

        if request.method == "HEAD":
            return

        eh_exportacao = caminho.startswith("/afd/download")
        eh_consulta = request.method == "GET" or caminho == "/afd/preview"

        if not eh_exportacao and not eh_consulta:
            return

        registrar_auditoria_request(
            request=request,
            acao="exportacao" if eh_exportacao else "consulta",
            recurso=caminho,
            detalhes={
                "metodo": request.method,
                "status_code": resposta.status_code,
                "parametros": dict(request.query_params)
            },
            sucesso=resposta.status_code < 400,
            status_code=resposta.status_code
        )
    
    async def dispatch(self, request: Request, call_next):
        if config_auth.admin_mode_livre:
            request.state.perfil = "Completo"
            request.state.usuario = "admin"
            resposta = await call_next(request)
            self.registrar_evento_requisicao(request, resposta)
            return resposta

        # Verificar se é rota pública
        eh_publica = any(
            request.url.path.startswith(rota) 
            for rota in self.ROTAS_PUBLICAS
        )
        
        if eh_publica:
            return await call_next(request)
        
        # Para rotas protegidas, verificar autenticação
        token = request.cookies.get("chronosnap_session")
        
        if not token or not sessao_manager.validar_sessao(token):
            # Não autenticado, redirecionar para login
            return RedirectResponse(url="/auth/login", status_code=303)

        sessao = sessao_manager.validar_sessao(token)
        request.state.perfil = sessao["perfil"]
        request.state.usuario = sessao.get("nome") or sessao.get("username")

        if (
            sessao["perfil"] != "Completo"
            and request.url.path.startswith(("/system", "/config"))
        ):

            if request.url.path.endswith("/list"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Permissão negada."}
                )

            return RedirectResponse(url="/", status_code=303)
        
        # Autenticado, continuar
        resposta = await call_next(request)
        self.registrar_evento_requisicao(request, resposta)
        return resposta


app.add_middleware(AutenticacaoMiddleware)


# ============================================================
# ARQUIVOS ESTÁTICOS
# ============================================================

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)


# ============================================================
# BANCO DE DADOS
# ============================================================

Base.metadata.create_all(bind=engine)

# Criar usuário admin padrão se não existir
db = SessionLocal()
try:
    garantir_configuracao_retencao(db)
    limpar_logs_auditoria(db)

    admin_existente = db.query(UsuarioSistema).filter(
        UsuarioSistema.username == "admin"
    ).first()
    
    if not admin_existente:
        admin = UsuarioSistema(
            username="admin",
            password_hash=hash_password("admin"),
            nome="Administrador",
            perfil="Completo",
            ativo=True
        )
        db.add(admin)
        db.commit()
        print("✅ Usuário admin criado com sucesso")
finally:
    db.close()

if "administrador" not in {
    coluna["name"]
    for coluna in inspect(engine).get_columns("funcionarios")
}:
    valor_booleano_falso = (
        "FALSE" if engine.dialect.name == "postgresql" else "0"
    )
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "ALTER TABLE funcionarios "
                "ADD COLUMN administrador BOOLEAN NOT NULL DEFAULT "
                f"{valor_booleano_falso}"
            )
        )

if "biometrias" not in {
    coluna["name"]
    for coluna in inspect(engine).get_columns("funcionarios")
}:
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "ALTER TABLE funcionarios ADD COLUMN biometrias TEXT"
            )
        )
colunas_funcionarios = {
    coluna["name"]
    for coluna in inspect(engine).get_columns("funcionarios")
}

for nome_coluna, definicao in (
    ("codigo", "INTEGER"),
    ("rfid", "INTEGER"),
    ("bars", "VARCHAR(100)"),
):
    if nome_coluna not in colunas_funcionarios:
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    f"ALTER TABLE funcionarios "
                    f"ADD COLUMN {nome_coluna} {definicao}"
                )
            )



# ============================================================
# REGISTRO DAS ROTAS
# ============================================================

app.include_router(afd_router)
app.include_router(users_router)
app.include_router(company_router)
app.include_router(system_router)
app.include_router(lojas_router)
app.include_router(dashboard_router)
app.include_router(funcionarios_router)
app.include_router(auth_router)
app.include_router(config_router)
app.include_router(licenca_router)