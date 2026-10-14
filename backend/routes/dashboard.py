from pathlib import Path
import ctypes
import os
import platform
import socket

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Loja
from services.monitor import intervalo_ping, obter_historico_latencia


BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

router = APIRouter()


def informacoes_servidor():
    memoria_total = None
    memoria_disponivel = None

    if platform.system() == "Windows":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        memoria = MEMORYSTATUSEX()
        memoria.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memoria)):
            memoria_total = memoria.ullTotalPhys
            memoria_disponivel = memoria.ullAvailPhys

    return {
        "nome": socket.gethostname(),
        "sistema": f"{platform.system()} {platform.release()}",
        "versao": platform.version(),
        "arquitetura": platform.machine(),
        "cpu": platform.processor() or platform.machine(),
        "nucleos": os.cpu_count() or 0,
        "memoria_total_gb": round(memoria_total / (1024 ** 3), 1) if memoria_total else None,
        "memoria_disponivel_gb": round(memoria_disponivel / (1024 ** 3), 1) if memoria_disponivel else None,
    }


def status_dashboard(db):

    lojas = (
        db.query(Loja)
        .order_by(Loja.numero)
        .all()
    )

    return lojas


@router.get("/")
async def dashboard(request: Request):

    db: Session = SessionLocal()

    try:

        lojas = status_dashboard(db)

        total = len(lojas)

        online = sum(
            1 for loja in lojas
            if loja.online
        )

        offline = total - online

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "lojas": lojas,
                "total_lojas": total,
                "lojas_online": online,
                "lojas_offline": offline,
                "ping_interval": intervalo_ping(),
                "servidor": informacoes_servidor()
            }
        )

    finally:

        db.close()


@router.get("/api/dashboard/status")
async def dashboard_status():

    db: Session = SessionLocal()

    try:

        lojas = status_dashboard(db)

        return JSONResponse({
            "total": len(lojas),
            "online": sum(1 for loja in lojas if loja.online),
            "offline": sum(1 for loja in lojas if not loja.online),
            "lojas": [
                {
                    "numero": loja.numero,
                    "nome": loja.nome,
                    "ip": loja.ip,
                    "porta": loja.porta or 443,
                    "online": bool(loja.online),
                    "tempo_resposta": loja.tempo_resposta,
                    "ultimo_teste": loja.ultimo_teste,
                    "mensagem": loja.mensagem_status or "",
                    "historico": obter_historico_latencia(loja.numero)
                }
                for loja in lojas
            ]
        })

    finally:

        db.close()