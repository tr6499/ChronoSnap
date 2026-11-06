import asyncio
import logging
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import SessionLocal
from routes.config import exigir_administrador
from services.auditoria import registrar_auditoria
from services.backup import (
    BACKUP_DIR,
    BACKUP_PATTERN,
    criar_backup,
    listar_backups,
    obter_configuracao,
    restaurar_backup,
    salvar_configuracao,
)


BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter()
logger = logging.getLogger(__name__)

DIAS_SEMANA = (
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
)


def _auditar(acao, usuario, detalhes):
    db = SessionLocal()
    try:
        resultado = registrar_auditoria(
            acao=acao,
            recurso="backup",
            usuario=usuario,
            detalhes=detalhes,
            db=db,
        )
        if resultado is None:
            logger.error("Não foi possível registrar a ação %s de backup.", acao)
    finally:
        db.close()


@router.get("/backup")
async def pagina_backup(request: Request):
    exigir_administrador(request)
    try:
        configuracao = obter_configuracao()
        backups = listar_backups()
        erro = request.query_params.get("erro")
    except (OSError, RuntimeError) as exc:
        configuracao = {
            "enabled": False,
            "period": "weekly",
            "weekday": 6,
            "time": "02:00",
            "retention": 30,
            "last_run": None,
        }
        backups = []
        erro = str(exc)
    return templates.TemplateResponse(
        request=request,
        name="backup.html",
        context={
            "configuracao": configuracao,
            "backups": backups,
            "backup_dir": str(BACKUP_DIR),
            "dias_semana": enumerate(DIAS_SEMANA),
            "erro": erro,
            "sucesso": request.query_params.get("sucesso"),
        },
    )


@router.post("/backup/gerar")
async def gerar_backup(request: Request):
    usuario = exigir_administrador(request)
    try:
        arquivo = await asyncio.to_thread(criar_backup)
        _auditar(
            "criar_backup",
            usuario,
            {"arquivo": arquivo.name, "origem": "manual"},
        )
    except Exception as exc:
        logger.exception("Falha ao gerar backup.")
        return RedirectResponse(
            f"/backup?erro={quote_plus(f'Não foi possível gerar o backup: {exc}')}",
            status_code=303,
        )
    return RedirectResponse(
        f"/backup?sucesso={quote_plus(f'Backup criado: {arquivo.name}')}",
        status_code=303,
    )


@router.post("/backup/restaurar")
async def restaurar_backup_route(
    request: Request,
    arquivo: UploadFile = File(...),
    confirmar: str = Form("false"),
):
    usuario = exigir_administrador(request)
    if confirmar != "true":
        await arquivo.close()
        return RedirectResponse(
            "/backup?erro=Confirme+a+substitui%C3%A7%C3%A3o+dos+dados+antes+de+restaurar.",
            status_code=303,
        )
    try:
        await asyncio.to_thread(restaurar_backup, arquivo.file)
        _auditar(
            "restaurar_backup",
            usuario,
            {"arquivo": Path(arquivo.filename or "backup.zip").name},
        )
    except Exception as exc:
        logger.exception("Falha ao restaurar backup.")
        return RedirectResponse(
            f"/backup?erro={quote_plus(f'Não foi possível restaurar o backup: {exc}')}",
            status_code=303,
        )
    finally:
        await arquivo.close()
    return RedirectResponse(
        "/backup?sucesso=Backup+restaurado.+Os+dados+do+banco+foram+substitu%C3%ADdos.",
        status_code=303,
    )


@router.post("/backup/configuracao")
async def salvar_configuracao_backup(
    request: Request,
    enabled: str = Form("false"),
    period: str = Form("weekly"),
    weekday: int = Form(6),
    horario: str = Form("02:00"),
    retention: str = Form("30"),
):
    usuario = exigir_administrador(request)
    try:
        configuracao = salvar_configuracao(
            {
                "enabled": enabled == "true",
                "period": period,
                "weekday": weekday,
                "time": horario,
                "retention": retention,
            }
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.exception("Falha ao salvar a configuração do backup.")
        return RedirectResponse(
            f"/backup?erro={quote_plus(f'Não foi possível salvar as opções: {exc}')}",
            status_code=303,
        )
    _auditar(
        "configurar_backup",
        usuario,
        {
            "automatico": configuracao["enabled"],
            "periodo": configuracao["period"],
            "retencao": configuracao["retention"],
        },
    )
    return RedirectResponse(
        "/backup?sucesso=Op%C3%A7%C3%B5es+de+backup+salvas.",
        status_code=303,
    )


@router.get("/backup/baixar/{nome}")
async def baixar_backup(request: Request, nome: str):
    exigir_administrador(request)
    if not BACKUP_PATTERN.fullmatch(nome):
        raise HTTPException(status_code=404, detail="Backup não encontrado.")
    arquivo = BACKUP_DIR / nome
    if not arquivo.is_file() or arquivo.resolve().parent != BACKUP_DIR.resolve():
        raise HTTPException(status_code=404, detail="Backup não encontrado.")
    return FileResponse(
        arquivo,
        media_type="application/zip",
        filename=nome,
    )
