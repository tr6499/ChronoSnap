import asyncio
import os
from collections import defaultdict, deque
from datetime import datetime

from database import SessionLocal
from models import Loja
from services.conexao import testar_conexao


DEFAULT_INTERVAL = 30
HISTORICO_MAXIMO = 20
historico_latencia = defaultdict(lambda: deque(maxlen=HISTORICO_MAXIMO))


def obter_historico_latencia(numero):
    return list(historico_latencia[str(numero)])


def intervalo_ping():

    try:
        return max(
            5,
            int(os.getenv("AFD_PING_INTERVAL", DEFAULT_INTERVAL))
        )
    except ValueError:
        return DEFAULT_INTERVAL


def atualizar_status_lojas():

    db = SessionLocal()

    try:

        lojas = db.query(Loja).order_by(Loja.numero).all()

        for loja in lojas:

            resultado = testar_conexao(
                loja.ip,
                porta=loja.porta or 443,
                timeout=5
            )

            loja.online = resultado["online"]
            loja.tempo_resposta = resultado.get("tempo_ms")
            loja.mensagem_status = resultado.get("mensagem", "")[:300]
            loja.ultimo_teste = datetime.now().strftime(
                "%d/%m/%Y %H:%M:%S"
            )
            historico_latencia[str(loja.numero)].append({
                "horario": datetime.now().isoformat(timespec="seconds"),
                "tempo_resposta": loja.tempo_resposta,
                "online": bool(loja.online)
            })

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


async def monitorar_lojas():

    while True:

        try:
            await asyncio.to_thread(atualizar_status_lojas)
        except Exception:
            pass

        await asyncio.sleep(intervalo_ping())
