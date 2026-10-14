from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from database import SessionLocal
from models import Loja
from services.idclass import IDClass


router = APIRouter(
    prefix="/system",
    tags=["System"]
)

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)


class DataHoraPayload(BaseModel):
    day: int
    month: int
    year: int
    hour: int
    minute: int
    second: int = 0
    timezone: str | None = "-0300"


def criar_equipamento(loja):

    return IDClass(
        ip=loja.ip,
        username=loja.usuario or "admin",
        password=loja.senha or "7070"
    )


def buscar_loja(numero: int):

    db = SessionLocal()

    try:

        loja = (
            db.query(Loja)
            .filter(Loja.numero == numero)
            .first()
        )

        if not loja:
            raise HTTPException(
                status_code=404,
                detail="Loja não encontrada"
            )

        return loja

    finally:

        db.close()


@router.get("")
async def system_dashboard(request: Request):

    db = SessionLocal()

    try:

        empresas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="datetime.html",
            context={
                "empresas": empresas
            }
        )

    finally:

        db.close()


@router.get("/datetime")
async def system_datetime_page(request: Request):

    db = SessionLocal()

    try:

        empresas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="datetime.html",
            context={
                "empresas": empresas
            }
        )

    finally:

        db.close()


@router.get("/info")
async def system_info_page(request: Request):

    db = SessionLocal()

    try:

        empresas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="system-info.html",
            context={
                "empresas": empresas
            }
        )

    finally:

        db.close()


@router.get("/rep")
async def system_rep_page(request: Request):

    db = SessionLocal()

    try:

        empresas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="rep-info.html",
            context={
                "empresas": empresas
            }
        )

    finally:

        db.close()


@router.get("/network")
async def system_network_page(request: Request):

    db = SessionLocal()

    try:

        empresas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="network-config.html",
            context={
                "empresas": empresas
            }
        )

    finally:

        db.close()


@router.get("/idcloud")
async def system_idcloud_page(request: Request):

    db = SessionLocal()

    try:

        empresas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="idcloud-settings.html",
            context={
                "empresas": empresas
            }
        )

    finally:

        db.close()


@router.get("/information")
async def system_information_page(request: Request):

    db = SessionLocal()

    try:

        empresas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="sistema.html",
            context={
                "empresas": empresas
            }
        )

    finally:

        db.close()


@router.get("/{numero}/about")
async def get_about(numero: int):

    loja = buscar_loja(numero)

    equipamento = criar_equipamento(loja)
    try:
        equipamento.login_device()
        return equipamento.get_about()
    finally:
        equipamento.logout()


@router.get("/{numero}/information")
async def get_system_information(numero: int):

    loja = buscar_loja(numero)

    equipamento = criar_equipamento(loja)
    try:
        equipamento.login_device()
        return equipamento.get_system_information()
    finally:
        equipamento.logout()


@router.get("/{numero}/rep-information")
async def get_rep_information(numero: int):

    equipamento = None
    try:

        loja = buscar_loja(numero)

        equipamento = criar_equipamento(loja)
        equipamento.login_device()

        return equipamento.get_rep_information()

    except HTTPException:
        raise

    except Exception as erro:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível consultar as informações do REP: {erro}"
        )

    finally:
        if equipamento:
            equipamento.logout()


@router.post("/{numero}/idcloud")
async def set_idcloud(
    numero: int,
    enable: bool = Body(..., embed=True)
):

    equipamento = None
    try:

        loja = buscar_loja(numero)

        equipamento = criar_equipamento(loja)
        equipamento.login_device()

        return equipamento.set_idcloud(enable)

    except HTTPException:
        raise

    except Exception as erro:
        acao = "ativar" if enable else "desativar"
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível {acao} o iDCloud: {erro}"
        )

    finally:
        if equipamento:
            equipamento.logout()


@router.get("/{numero}/idcloud")
async def get_idcloud(numero: int):

    equipamento = None
    try:

        loja = buscar_loja(numero)

        equipamento = criar_equipamento(loja)
        equipamento.login_device()

        return equipamento.get_idcloud()

    except HTTPException:
        raise

    except Exception as erro:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível consultar o estado do iDCloud: {erro}"
        )

    finally:
        if equipamento:
            equipamento.logout()


@router.get("/{numero}/network")
async def get_system_network(numero: int):

    equipamento = None
    try:

        loja = buscar_loja(numero)

        equipamento = criar_equipamento(loja)
        equipamento.login_device()

        return equipamento.get_system_network()

    except HTTPException:
        raise

    except Exception as erro:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível consultar a configuração de rede: {erro}"
        )

    finally:
        if equipamento:
            equipamento.logout()


@router.post("/{numero}/network")
async def set_system_network(
    numero: int,
    dados: dict
):

    equipamento = None
    try:

        loja = buscar_loja(numero)
        equipamento = criar_equipamento(loja)
        equipamento.login_device()

        payload = {
            chave: valor
            for chave, valor in dados.items()
            if valor is not None and valor != ""
        }

        return equipamento.set_system_network(payload)

    except HTTPException:
        raise

    except Exception as erro:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível salvar a configuração de rede: {erro}"
        )

    finally:
        if equipamento:
            equipamento.logout()


@router.get("/{numero}/datetime")
async def get_system_date_time(numero: int):

    loja = buscar_loja(numero)

    equipamento = criar_equipamento(loja)
    try:
        equipamento.login_device()
        return equipamento.get_system_date_time()
    finally:
        equipamento.logout()


@router.get("/{numero}/serial")
async def get_serial_number(numero: int):

    loja = buscar_loja(numero)

    equipamento = criar_equipamento(loja)
    try:
        equipamento.login_device()
        return {
            "serial": equipamento.serial_number()
        }
    finally:
        equipamento.logout()


@router.get("/{numero}/mac")
async def get_mac_address(numero: int):

    loja = buscar_loja(numero)

    equipamento = criar_equipamento(loja)
    try:
        equipamento.login_device()
        return {
            "mac": equipamento.mac_address()
        }
    finally:
        equipamento.logout()


@router.get("/{numero}/firmware")
async def get_firmware_version(numero: int):

    loja = buscar_loja(numero)

    equipamento = criar_equipamento(loja)
    try:
        equipamento.login_device()
        return {
            "versionFW": equipamento.firmware_version()
        }
    finally:
        equipamento.logout()


@router.get("/{numero}/mrp")
async def get_mrp_version(numero: int):

    loja = buscar_loja(numero)

    equipamento = criar_equipamento(loja)
    try:
        equipamento.login_device()
        return {
            "versionMRP": equipamento.mrp_version()
        }
    finally:
        equipamento.logout()


@router.post("/{numero}/datetime")
async def set_system_date_time(
    numero: int,
    dados: DataHoraPayload
):

    equipamento = None
    try:

        loja = buscar_loja(numero)

        layout = (loja.afd_layout or "legado").strip().lower()
        mode = 671 if layout in ("671", "portaria671") else 0

        equipamento = criar_equipamento(loja)
        equipamento.login_device()

        return equipamento.set_system_date_time(
            day=dados.day,
            month=dados.month,
            year=dados.year,
            hour=dados.hour,
            minute=dados.minute,
            second=dados.second,
            timezone=dados.timezone,
            mode=mode
        )

    except HTTPException:
        raise

    except Exception as erro:
        raise HTTPException(
            status_code=502,
            detail=f"Não foi possível ajustar a data e hora: {erro}"
        )

    finally:
        if equipamento:
            equipamento.logout()


@router.post("/datetime/sync-all")
async def sync_all_date_time():

    db = SessionLocal()
    agora = datetime.now()
    resultados = []

    try:

        empresas = db.query(Loja).order_by(Loja.numero).all()

        for empresa in empresas:
            equipamento = None
            try:
                layout = (empresa.afd_layout or "legado").strip().lower()
                mode = 671 if layout in ("671", "portaria671") else 0
                equipamento = criar_equipamento(empresa)
                equipamento.login_device()
                resposta = equipamento.set_system_date_time(
                    day=agora.day,
                    month=agora.month,
                    year=agora.year,
                    hour=agora.hour,
                    minute=agora.minute,
                    second=agora.second,
                    timezone="-0300",
                    mode=mode
                )
                resultados.append({
                    "empresa": empresa.numero,
                    "nome": empresa.nome,
                    "success": True,
                    "resposta": resposta
                })
            except Exception as erro:
                resultados.append({
                    "empresa": empresa.numero,
                    "nome": empresa.nome,
                    "success": False,
                    "erro": str(erro)
                })
            finally:
                if equipamento:
                    equipamento.logout()

        return {
            "success": all(resultado["success"] for resultado in resultados),
            "data_hora": agora.strftime("%d/%m/%Y %H:%M:%S"),
            "resultados": resultados
        }

    finally:
        db.close()

