import logging
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


def testar_conexao(
    ip,
    porta=443,
    usuario="admin",
    senha="",
    timeout=5
):
    host = str(ip).strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if int(porta or 443) != 443:
        host = f"{host}:{int(porta)}"

    base_url = f"https://{host}"
    inicio = time.perf_counter()
    session_token = None

    try:
        resposta = requests.post(
            f"{base_url}/login.fcgi",
            json={
                "login": usuario or "admin",
                "password": senha or ""
            },
            verify=False,
            timeout=timeout
        )
        tempo_ms = int((time.perf_counter() - inicio) * 1000)

        if resposta.status_code in (401, 403):
            return {
                "status": "error",
                "online": False,
                "tempo_ms": tempo_ms,
                "mensagem": (
                    "A API do relógio respondeu, mas recusou as credenciais."
                )
            }

        if not resposta.ok:
            return {
                "status": "error",
                "online": False,
                "tempo_ms": tempo_ms,
                "mensagem": (
                    "A API do relógio respondeu com HTTP "
                    f"{resposta.status_code}."
                )
            }

        try:
            dados = resposta.json()
        except ValueError:
            return {
                "status": "error",
                "online": False,
                "tempo_ms": tempo_ms,
                "mensagem": "A API respondeu, mas retornou dados inválidos."
            }

        session_token = dados.get("session") if isinstance(dados, dict) else None
        if not session_token:
            return {
                "status": "error",
                "online": False,
                "tempo_ms": tempo_ms,
                "mensagem": (
                    "A API respondeu, mas não confirmou a autenticação."
                )
            }

        mensagem = "API do relógio autenticada com sucesso."
        try:
            logout = requests.post(
                f"{base_url}/logout.fcgi",
                params={"session": session_token},
                json={},
                verify=False,
                timeout=timeout
            )
            if not logout.ok:
                logger.warning(
                    "A API do relógio %s respondeu ao login, mas o logout "
                    "retornou HTTP %s.",
                    ip,
                    logout.status_code
                )
        except requests.RequestException:
            logger.warning(
                "A API do relógio %s respondeu ao login, mas não foi possível "
                "encerrar a sessão de verificação.",
                ip,
                exc_info=True
            )

        return {
            "status": "online",
            "online": True,
            "tempo_ms": tempo_ms,
            "mensagem": mensagem
        }

    except requests.exceptions.SSLError as erro:
        return {
            "status": "error",
            "online": False,
            "tempo_ms": None,
            "mensagem": f"Falha na negociação HTTPS: {erro}"
        }
    except requests.exceptions.Timeout:
        return {
            "status": "timeout",
            "online": False,
            "tempo_ms": None,
            "mensagem": (
                "A API não respondeu dentro do prazo; não foi possível "
                "confirmar o estado do relógio."
            )
        }
    except requests.exceptions.ConnectionError as erro:
        return {
            "status": "offline",
            "online": False,
            "tempo_ms": None,
            "mensagem": f"Não foi possível conectar à API do relógio: {erro}"
        }
    except requests.RequestException as erro:
        return {
            "status": "unknown",
            "online": False,
            "tempo_ms": None,
            "mensagem": f"Não foi possível confirmar o estado do relógio: {erro}"
        }
