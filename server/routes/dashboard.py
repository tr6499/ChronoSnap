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
from services.banco_dados import configuracao_publica
from services.monitor import (
    estado_atual_loja,
    intervalo_ping,
    obter_historico_latencia
)


BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

router = APIRouter()


def informacoes_servidor():
    memoria_total = None
    memoria_disponivel = None
    sistema = platform.system()
    identificador_cpu = platform.processor()
    cpu = identificador_cpu or platform.machine()
    cpu_normalizada = identificador_cpu.casefold()

    if any(marca in cpu_normalizada for marca in ("genuineintel", "intel")):
        cpu_fabricante = "Intel"
    elif any(
        marca in cpu_normalizada
        for marca in ("authenticamd", "amd64 family", "ryzen", "epyc", "amd ")
    ):
        cpu_fabricante = "AMD"
    elif "apple" in cpu_normalizada:
        cpu_fabricante = "Apple"
    elif "arm" in cpu_normalizada or platform.machine().casefold().startswith(
        ("arm", "aarch")
    ):
        cpu_fabricante = "ARM"
    else:
        cpu_fabricante = "Outro"

    sistema_icones = {
        "windows": "windows",
        "linux": "linux",
        "darwin": "apple",
    }

    if sistema == "Windows":
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
        "sistema": f"{sistema} {platform.release()}",
        "sistema_icone": sistema_icones.get(sistema.casefold()),
        "versao": platform.version(),
        "arquitetura": platform.machine(),
        "cpu": cpu,
        "cpu_fabricante": cpu_fabricante,
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


def resumir_status(statuses):
    estados = list(statuses.values())
    return {
        "online": estados.count("online"),
        "offline": estados.count("offline"),
        "error": estados.count("error"),
        "timeout": estados.count("timeout"),
        "unknown": estados.count("unknown"),
        "stale": estados.count("stale")
    }


@router.get("/")
async def dashboard(request: Request):

    db: Session = SessionLocal()

    try:

        lojas = status_dashboard(db)
        status_por_loja = {
            loja.id: estado_atual_loja(loja)
            for loja in lojas
        }
        total = len(lojas)
        resumo = resumir_status(status_por_loja)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "lojas": lojas,
                "total_lojas": total,
                "status_lojas": status_por_loja,
                "lojas_online": resumo["online"],
                "lojas_offline": resumo["offline"],
                "lojas_sem_dados": resumo["stale"],
                "lojas_com_erro": (
                    resumo["error"]
                    + resumo["timeout"]
                    + resumo["unknown"]
                ),
                "lojas_com_timeout": resumo["timeout"],
                "lojas_com_erro_api": resumo["error"],
                "lojas_com_estado_desconhecido": resumo["unknown"],
                "ping_interval": intervalo_ping(),
                "servidor": informacoes_servidor(),
                "banco": configuracao_publica(),
            }
        )

    finally:

        db.close()


@router.get("/api/dashboard/status")
async def dashboard_status():

    db: Session = SessionLocal()

    try:

        lojas = status_dashboard(db)
        status_por_loja = {
            loja.id: estado_atual_loja(loja)
            for loja in lojas
        }
        resumo = resumir_status(status_por_loja)
        return JSONResponse({
            "total": len(lojas),
            **resumo,
            "lojas": [
                {
                    "numero": loja.numero,
                    "nome": loja.nome,
                    "ip": loja.ip,
                    "porta": loja.porta or 443,
                    "status": status_por_loja[loja.id],
                    "online": status_por_loja[loja.id] == "online",
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