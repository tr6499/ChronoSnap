import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def testar_conexao(ip, porta=443, timeout=10):
    url = f"https://{ip}:{porta}/"

    inicio = time.perf_counter()

    try:
        resposta = requests.get(
            url,
            timeout=timeout,
            verify=False
        )

        fim = time.perf_counter()

        tempo_ms = int((fim - inicio) * 1000)

        return {
            "online": True,
            "status_code": resposta.status_code,
            "tempo_ms": tempo_ms,
            "mensagem": f"HTTPS respondeu HTTP {resposta.status_code}"
        }

    except requests.exceptions.ConnectTimeout:
        return {
            "online": False,
            "status_code": None,
            "tempo_ms": None,
            "mensagem": "Tempo limite de conexão"
        }

    except requests.exceptions.ConnectionError as erro:
        return {
            "online": False,
            "status_code": None,
            "tempo_ms": None,
            "mensagem": f"Falha de conexão: {erro}"
        }

    except Exception as erro:
        return {
            "online": False,
            "status_code": None,
            "tempo_ms": None,
            "mensagem": f"Erro: {erro}"
        }