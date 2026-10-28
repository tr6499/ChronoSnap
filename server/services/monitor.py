import asyncio
import logging
import os
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from database import SessionLocal
from models import Loja
from services.conexao import testar_conexao


DEFAULT_INTERVAL = 30
HISTORICO_MAXIMO = 20
MAXIMO_VERIFICACOES_PARALELAS = 10
historico_latencia = defaultdict(lambda: deque(maxlen=HISTORICO_MAXIMO))
logger = logging.getLogger(__name__)


def obter_historico_latencia(numero):
    return list(historico_latencia[str(numero)])


def intervalo_ping():
    try:
        return max(
            5,
            int(os.getenv("AFD_PING_INTERVAL", DEFAULT_INTERVAL))
        )
    except ValueError:
        logger.exception("AFD_PING_INTERVAL deve ser um número inteiro.")
        return DEFAULT_INTERVAL


def estado_atual_loja(loja, agora=None):
    agora = agora or datetime.now()
    if not loja.ultimo_teste:
        return "stale"

    try:
        try:
            ultima_verificacao = datetime.fromisoformat(loja.ultimo_teste)
        except ValueError:
            ultima_verificacao = datetime.strptime(
                loja.ultimo_teste,
                "%d/%m/%Y %H:%M:%S"
            )
    except (TypeError, ValueError):
        return "stale"

    if ultima_verificacao.tzinfo is not None:
        ultima_verificacao = ultima_verificacao.replace(tzinfo=None)
    if (agora - ultima_verificacao).total_seconds() > max(
        intervalo_ping() * 3,
        90
    ):
        return "stale"

    estado = loja.status_conexao
    if estado in ("online", "offline", "error", "timeout", "unknown"):
        return estado
    return "stale"


def _testar_loja(loja):
    return testar_conexao(
        loja.ip,
        porta=loja.porta or 443,
        usuario=loja.usuario or "admin",
        senha=loja.senha or "",
        timeout=5
    )


def atualizar_status_lojas():
    db = SessionLocal()
    try:
        lojas = db.query(Loja).order_by(Loja.numero).all()
        if not lojas:
            return

        with ThreadPoolExecutor(
            max_workers=min(MAXIMO_VERIFICACOES_PARALELAS, len(lojas))
        ) as executor:
            verificacoes = [
                executor.submit(_testar_loja, loja)
                for loja in lojas
            ]
            for loja, verificacao in zip(lojas, verificacoes):
                try:
                    resultado = verificacao.result()
                except Exception as erro:
                    logger.exception(
                        "Falha inesperada ao verificar o relógio da empresa "
                        "%s (%s).",
                        loja.numero,
                        loja.ip
                    )
                    resultado = {
                        "status": "unknown",
                        "online": False,
                        "tempo_ms": None,
                        "mensagem": (
                            "Falha ao executar a verificação: "
                            f"{erro}"
                        )
                    }

                loja.status_conexao = resultado["status"]
                loja.online = resultado["status"] == "online"
                loja.tempo_resposta = resultado.get("tempo_ms")
                loja.mensagem_status = resultado.get("mensagem", "")[:300]
                agora = datetime.now()
                loja.ultimo_teste = agora.isoformat(timespec="seconds")
                historico_latencia[str(loja.numero)].append({
                    "horario": agora.isoformat(timespec="seconds"),
                    "tempo_resposta": loja.tempo_resposta,
                    "online": bool(loja.online),
                    "status": loja.status_conexao
                })

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Falha ao atualizar o estado dos relógios.")
        raise
    finally:
        db.close()


async def monitorar_lojas():
    while True:
        try:
            await asyncio.to_thread(atualizar_status_lojas)
        except Exception:
            logger.exception(
                "O ciclo de monitoramento dos relógios falhou; os estados "
                "serão marcados como desatualizados até uma nova verificação."
            )

        await asyncio.sleep(intervalo_ping())
