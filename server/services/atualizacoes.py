import hashlib
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import certifi

from app_paths import DATA_DIR


VERSAO_ATUAL = "1.0.10"
RELEASE_API_URL = "https://api.github.com/repos/tr6499/ChronoSnap/releases/latest"
RELEASES_URL = "https://github.com/tr6499/ChronoSnap/releases"
MAX_INSTALLER_SIZE = 500 * 1024 * 1024
ARQUIVO_CONFIG_ATUALIZACAO = DATA_DIR / "atualizacoes.json"


class ErroAtualizacao(Exception):
    pass


def _criar_contexto_ssl():
    contexto = ssl.create_default_context()
    contexto.load_verify_locations(cafile=certifi.where())
    return contexto


def ler_modo_atualizacao():
    try:
        configuracao = json.loads(
            ARQUIVO_CONFIG_ATUALIZACAO.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return "manual"
    except (OSError, json.JSONDecodeError) as exc:
        raise ErroAtualizacao(f"Não foi possível ler o modo de atualização: {exc}") from exc
    if not isinstance(configuracao, dict) or configuracao.get("modo") not in (
        "manual",
        "automatico",
    ):
        raise ErroAtualizacao("A configuração do modo de atualização é inválida.")
    return configuracao["modo"]


def salvar_modo_atualizacao(modo):
    if modo not in ("manual", "automatico"):
        raise ErroAtualizacao("Modo de atualização inválido.")
    temporario = ARQUIVO_CONFIG_ATUALIZACAO.with_suffix(".json.tmp")
    try:
        temporario.write_text(
            json.dumps({"modo": modo}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporario.replace(ARQUIVO_CONFIG_ATUALIZACAO)
    except OSError as exc:
        temporario.unlink(missing_ok=True)
        raise ErroAtualizacao(f"Não foi possível salvar o modo de atualização: {exc}") from exc


def _versao_numerica(valor):
    correspondencia = re.search(r"(\d+)\.(\d+)\.(\d+)", str(valor or ""))
    if not correspondencia:
        raise ErroAtualizacao("A versão publicada no GitHub não é válida.")
    return tuple(int(parte) for parte in correspondencia.groups())


def obter_ultima_release(timeout=15):
    requisicao = Request(
        RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ChronoSnap-Updater",
        },
    )
    try:
        with urlopen(
            requisicao,
            timeout=timeout,
            context=_criar_contexto_ssl(),
        ) as resposta:
            release = json.loads(resposta.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErroAtualizacao(f"Não foi possível consultar as atualizações do GitHub: {exc}") from exc

    if not isinstance(release, dict):
        raise ErroAtualizacao("O GitHub retornou dados de release em formato inválido.")
    if release.get("draft") or release.get("prerelease"):
        raise ErroAtualizacao("A última versão publicada não é uma versão estável.")

    versao = _versao_numerica(release.get("tag_name"))
    versao_atual = _versao_numerica(VERSAO_ATUAL)
    versao_texto = ".".join(str(parte) for parte in versao)
    nome_instalador = f"ChronoSnap-Setup-{versao_texto}.exe"
    assets = release.get("assets")
    if not isinstance(assets, list):
        assets = []
    asset = next(
        (
            item
            for item in assets
            if isinstance(item, dict)
            and item.get("name") == nome_instalador
        ),
        None,
    )

    instalador = None
    if asset:
        url = asset.get("browser_download_url", "")
        partes_url = urlparse(url)
        if (
            partes_url.scheme == "https"
            and partes_url.hostname == "github.com"
            and partes_url.path.startswith("/tr6499/ChronoSnap/releases/download/")
        ):
            checksum = (asset.get("digest") or "").removeprefix("sha256:").lower()
            instalador = {
                "nome": nome_instalador,
                "url": url,
                "sha256": checksum,
                "tamanho": asset.get("size"),
            }

    pagina_release = release.get("html_url") or RELEASES_URL
    partes_pagina = urlparse(pagina_release)
    if (
        partes_pagina.scheme != "https"
        or partes_pagina.hostname != "github.com"
        or not partes_pagina.path.startswith("/tr6499/ChronoSnap/releases/")
    ):
        pagina_release = RELEASES_URL

    return {
        "versao_atual": VERSAO_ATUAL,
        "versao_disponivel": versao_texto,
        "atualizacao_disponivel": versao > versao_atual,
        "nome": str(release.get("name") or f"ChronoSnap {versao_texto}"),
        "notas": str(release.get("body") or "Esta versão não possui notas de lançamento."),
        "pagina_release": pagina_release,
        "publicada_em": release.get("published_at"),
        "instalador": instalador,
        "instalador_verificado": bool(
            instalador and re.fullmatch(r"[a-f0-9]{64}", instalador["sha256"])
        ),
    }


def baixar_instalador(release, destino):
    instalador = release.get("instalador") or {}
    url = instalador.get("url", "")
    digest_esperado = instalador.get("sha256", "").lower()
    partes_url = urlparse(url)
    if (
        partes_url.scheme != "https"
        or partes_url.hostname != "github.com"
        or not partes_url.path.startswith("/tr6499/ChronoSnap/releases/download/")
    ):
        raise ErroAtualizacao("O endereço do instalador da release não é confiável.")
    if not re.fullmatch(r"[a-f0-9]{64}", digest_esperado):
        raise ErroAtualizacao(
            "A release não publicou um checksum SHA-256 válido para o instalador."
        )

    requisicao = Request(url, headers={"User-Agent": "ChronoSnap-Updater"})
    destino = destino.resolve()
    temporario = destino.with_name(destino.name + ".part")
    if destino.is_file():
        digest_existente = hashlib.sha256()
        with destino.open("rb") as arquivo_existente:
            for bloco in iter(lambda: arquivo_existente.read(1024 * 1024), b""):
                digest_existente.update(bloco)
        if digest_existente.hexdigest() == digest_esperado:
            return destino
    digest = hashlib.sha256()
    total = 0
    try:
        with urlopen(
            requisicao,
            timeout=30,
            context=_criar_contexto_ssl(),
        ) as resposta, temporario.open("wb") as arquivo:
            comprimento = resposta.headers.get("Content-Length")
            if comprimento and int(comprimento) > MAX_INSTALLER_SIZE:
                raise ErroAtualizacao("O instalador ultrapassa o tamanho máximo permitido.")
            while True:
                bloco = resposta.read(1024 * 1024)
                if not bloco:
                    break
                total += len(bloco)
                if total > MAX_INSTALLER_SIZE:
                    raise ErroAtualizacao("O instalador ultrapassa o tamanho máximo permitido.")
                digest.update(bloco)
                arquivo.write(bloco)
        if total == 0:
            raise ErroAtualizacao("O GitHub retornou um instalador vazio.")
        if digest.hexdigest() != digest_esperado:
            raise ErroAtualizacao("A verificação de integridade do instalador falhou.")
        temporario.replace(destino)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        temporario.unlink(missing_ok=True)
        if isinstance(exc, ErroAtualizacao):
            raise
        raise ErroAtualizacao(f"Não foi possível baixar o instalador: {exc}") from exc
    except ErroAtualizacao:
        temporario.unlink(missing_ok=True)
        raise
    return destino
