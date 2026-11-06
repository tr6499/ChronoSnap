import asyncio
import base64
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path, PurePosixPath

from sqlalchemy import inspect, select, text

from app_paths import DATA_DIR
from database import DATABASE_CONFIG, DATABASE_CONFIG_FILE, Base, engine
import models  # noqa: F401  registra as tabelas em Base.metadata
import models_usuarios  # noqa: F401
from services.atualizacoes import VERSAO_ATUAL
from services.banco_dados import _reiniciar_sequencia


BACKUP_DIR = DATA_DIR / "backups"
BACKUP_SETTINGS_FILE = DATA_DIR / "backup_settings.json"
BACKUP_PATTERN = re.compile(r"chronosnap_backup_\d{8}_\d{6}_\d{6}\.zip")
FORMAT_VERSION = 1
MAX_UPLOAD_SIZE = 2 * 1024 ** 3
MAX_UNCOMPRESSED_SIZE = 10 * 1024 ** 3
MAX_ARCHIVE_FILES = 10000
_backup_lock = threading.Lock()
logger = logging.getLogger(__name__)

DEFAULT_SETTINGS = {
    "enabled": False,
    "period": "weekly",
    "weekday": 6,
    "time": "02:00",
    "retention": 30,
    "last_run": None,
}


def _normalizar_configuracao(dados):
    if not isinstance(dados, dict):
        raise ValueError("A configuração do backup deve ser um objeto.")
    enabled = dados.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("O estado do backup automático é inválido.")
    period = dados.get("period", DEFAULT_SETTINGS["period"])
    if period not in ("daily", "weekly"):
        raise ValueError("A periodicidade do backup é inválida.")
    try:
        weekday = int(dados.get("weekday", DEFAULT_SETTINGS["weekday"]))
        retention = dados.get("retention", DEFAULT_SETTINGS["retention"])
        if retention != "unlimited":
            retention = int(retention)
    except (TypeError, ValueError) as exc:
        raise ValueError("A configuração de retenção é inválida.") from exc
    if weekday not in range(7):
        raise ValueError("O dia da semana do backup é inválido.")
    if retention != "unlimited" and retention not in (7, 30, 90):
        raise ValueError("A retenção deve ser 7, 30, 90 backups ou ilimitada.")
    horario = dados.get("time", DEFAULT_SETTINGS["time"])
    try:
        if time.fromisoformat(horario).strftime("%H:%M") != horario:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("O horário do backup é inválido.") from exc
    ultima_execucao = dados.get("last_run")
    if ultima_execucao is not None:
        try:
            date.fromisoformat(ultima_execucao)
        except (TypeError, ValueError) as exc:
            raise ValueError("A última execução do backup é inválida.") from exc
    return {
        "enabled": enabled,
        "period": period,
        "weekday": weekday,
        "time": horario,
        "retention": retention,
        "last_run": ultima_execucao,
    }


def obter_configuracao():
    try:
        dados = json.loads(BACKUP_SETTINGS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Não foi possível ler a configuração do backup: {exc}") from exc
    try:
        return _normalizar_configuracao(dados)
    except ValueError as exc:
        raise RuntimeError(f"Configuração do backup inválida: {exc}") from exc


def salvar_configuracao(dados):
    atual = obter_configuracao()
    atual.update(dados)
    configuracao = _normalizar_configuracao(atual)
    BACKUP_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=BACKUP_SETTINGS_FILE.parent,
            prefix=".backup-settings-",
            suffix=".tmp",
            delete=False,
        ) as arquivo:
            temporario = Path(arquivo.name)
            json.dump(configuracao, arquivo, ensure_ascii=False, indent=2)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, BACKUP_SETTINGS_FILE)
    except OSError as exc:
        raise RuntimeError(f"Não foi possível salvar a configuração do backup: {exc}") from exc
    finally:
        if temporario and temporario.exists():
            temporario.unlink()
    return configuracao


def _codificar_valor(valor):
    if isinstance(valor, datetime):
        return {"__type__": "datetime", "value": valor.isoformat()}
    if isinstance(valor, date):
        return {"__type__": "date", "value": valor.isoformat()}
    if isinstance(valor, bytes):
        return {"__type__": "bytes", "value": base64.b64encode(valor).decode("ascii")}
    if isinstance(valor, Decimal):
        return {"__type__": "decimal", "value": str(valor)}
    raise TypeError(f"Tipo de dado não suportado no backup: {type(valor).__name__}")


def _decodificar_valor(valor):
    if not isinstance(valor, dict) or "__type__" not in valor:
        return valor
    tipo = valor["__type__"]
    conteudo = valor.get("value")
    if tipo == "datetime":
        return datetime.fromisoformat(conteudo)
    if tipo == "date":
        return date.fromisoformat(conteudo)
    if tipo == "bytes":
        return base64.b64decode(conteudo, validate=True)
    if tipo == "decimal":
        return Decimal(conteudo)
    raise ValueError("O backup contém um tipo de dado desconhecido.")


def _arquivos_de_dados():
    raiz = DATA_DIR.resolve()
    banco = (DATA_DIR / "banco").resolve()
    backups = BACKUP_DIR.resolve()
    for caminho in raiz.rglob("*"):
        if caminho.is_symlink():
            continue
        if not caminho.is_file():
            continue
        resolvido = caminho.resolve()
        if resolvido == DATABASE_CONFIG_FILE.resolve():
            relativo = caminho.relative_to(raiz)
            yield caminho, relativo
            continue
        if resolvido == BACKUP_SETTINGS_FILE.resolve():
            relativo = caminho.relative_to(raiz)
            yield caminho, relativo
            continue
        if resolvido.is_relative_to(backups) or resolvido.is_relative_to(banco):
            continue
        relativo = caminho.relative_to(raiz)
        yield caminho, relativo


def listar_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    arquivos = [
        caminho for caminho in BACKUP_DIR.iterdir()
        if caminho.is_file() and BACKUP_PATTERN.fullmatch(caminho.name)
    ]
    return [
        {
            "nome": caminho.name,
            "tamanho": caminho.stat().st_size,
            "criado_em": datetime.fromtimestamp(caminho.stat().st_mtime),
        }
        for caminho in sorted(arquivos, key=lambda item: item.stat().st_mtime, reverse=True)
    ]


def _aplicar_retencao(retencao):
    if retencao == "unlimited":
        return
    backups = listar_backups()
    for backup in backups[int(retencao):]:
        (BACKUP_DIR / backup["nome"]).unlink()


def criar_backup():
    with _backup_lock:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        nome = datetime.now().strftime("chronosnap_backup_%Y%m%d_%H%M%S_%f.zip")
        destino = BACKUP_DIR / nome
        temporario = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=BACKUP_DIR,
                prefix=".backup-",
                suffix=".tmp",
                delete=False,
            ) as arquivo:
                temporario = Path(arquivo.name)
            with zipfile.ZipFile(
                temporario, "w", compression=zipfile.ZIP_DEFLATED
            ) as arquivo_zip:
                arquivo_zip.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "format_version": FORMAT_VERSION,
                            "version": VERSAO_ATUAL,
                            "created_at": datetime.now().isoformat(),
                            "backend": DATABASE_CONFIG["backend"],
                        },
                        ensure_ascii=False,
                    ),
                )
                snapshot = {"tables": {}}
                with engine.connect() as conexao:
                    transacao = conexao.begin()
                    try:
                        for tabela in Base.metadata.sorted_tables:
                            snapshot["tables"][tabela.name] = [
                                dict(linha)
                                for linha in conexao.execute(
                                    select(tabela)
                                ).mappings()
                            ]
                    finally:
                        transacao.rollback()
                arquivo_zip.writestr(
                    "database.json",
                    json.dumps(snapshot, default=_codificar_valor, ensure_ascii=False),
                )
                for caminho, relativo in _arquivos_de_dados():
                    arquivo_zip.write(
                        caminho,
                        f"files/{relativo.as_posix()}",
                    )
            os.replace(temporario, destino)
            configuracao = obter_configuracao()
            _aplicar_retencao(configuracao["retention"])
            return destino
        except Exception:
            if temporario and temporario.exists():
                temporario.unlink()
            raise


def _validar_membros(arquivo_zip):
    membros = {}
    total = 0
    informacoes = arquivo_zip.infolist()
    if len(informacoes) > MAX_ARCHIVE_FILES:
        raise ValueError("O backup contém arquivos demais.")
    for info in informacoes:
        if info.is_dir():
            continue
        nome = info.filename
        caminho = PurePosixPath(nome)
        modo = info.external_attr >> 16
        if (
            "\\" in nome
            or ":" in nome
            or caminho.is_absolute()
            or ".." in caminho.parts
            or not caminho.parts
            or stat.S_ISLNK(modo)
            or info.flag_bits & 0x1
        ):
            raise ValueError("O backup contém um caminho ou arquivo inseguro.")
        if nome not in ("manifest.json", "database.json"):
            if caminho.parts[0] != "files" or len(caminho.parts) < 2:
                raise ValueError("O backup contém um item não reconhecido.")
        if nome in membros:
            raise ValueError("O backup contém nomes de arquivo duplicados.")
        membros[nome] = info
        total += info.file_size
        if total > MAX_UNCOMPRESSED_SIZE:
            raise ValueError("O conteúdo descompactado do backup excede o limite permitido.")
    if "manifest.json" not in membros or "database.json" not in membros:
        raise ValueError("O arquivo não contém um backup válido do ChronoSnap.")
    return membros


def _validar_snapshot(arquivo_zip, membros):
    try:
        manifest = json.loads(arquivo_zip.read(membros["manifest.json"]))
        snapshot = json.loads(arquivo_zip.read(membros["database.json"]))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("O backup está corrompido ou incompleto.") from exc
    if (
        manifest.get("format_version") != FORMAT_VERSION
        or manifest.get("backend") not in ("sqlite", "postgresql", "mysql", "mariadb", "mssql", "oracle")
    ):
        raise ValueError("A versão ou o banco de dados do backup não é compatível.")
    tabelas = {tabela.name: tabela for tabela in Base.metadata.sorted_tables}
    dados_tabelas = snapshot.get("tables")
    if not isinstance(dados_tabelas, dict) or set(dados_tabelas) != set(tabelas):
        raise ValueError("As tabelas do backup não correspondem a esta versão do ChronoSnap.")
    for nome, linhas in dados_tabelas.items():
        if not isinstance(linhas, list):
            raise ValueError(f"Os dados da tabela {nome} são inválidos.")
        colunas = set(tabelas[nome].c.keys())
        for linha in linhas:
            if not isinstance(linha, dict) or not set(linha).issubset(colunas):
                raise ValueError(f"Uma linha da tabela {nome} é inválida.")
    return snapshot


def _restaurar_tabelas(snapshot):
    tabelas = {tabela.name: tabela for tabela in Base.metadata.sorted_tables}
    nomes_banco = set(inspect(engine).get_table_names())
    ausentes = set(tabelas) - nomes_banco
    if ausentes:
        raise RuntimeError(
            "O banco ativo não possui as tabelas necessárias: "
            + ", ".join(sorted(ausentes))
        )
    sequencias_oracle = []
    with engine.begin() as conexao:
        for tabela in reversed(Base.metadata.sorted_tables):
            conexao.execute(tabela.delete())
        for tabela in Base.metadata.sorted_tables:
            linhas = [
                {
                    chave: _decodificar_valor(valor)
                    for chave, valor in linha.items()
                }
                for linha in snapshot["tables"][tabela.name]
            ]
            if not linhas:
                continue
            identity_insert = False
            if engine.dialect.name == "mssql":
                colunas = inspect(engine).get_columns(tabela.name)
                identity_insert = any(coluna.get("identity") for coluna in colunas)
                if identity_insert:
                    nome_tabela = engine.dialect.identifier_preparer.quote(tabela.name)
                    conexao.exec_driver_sql(
                        f"SET IDENTITY_INSERT {nome_tabela} ON"
                    )
            try:
                conexao.execute(tabela.insert(), linhas)
            finally:
                if identity_insert:
                    conexao.exec_driver_sql(
                        f"SET IDENTITY_INSERT {nome_tabela} OFF"
                    )
            if engine.dialect.name == "postgresql":
                for coluna in tabela.primary_key.columns:
                    if coluna.autoincrement:
                        _reiniciar_sequencia(
                            conexao,
                            engine.dialect.name,
                            tabela.name,
                            coluna.name,
                            max(linha[coluna.name] for linha in linhas),
                        )
            elif engine.dialect.name == "oracle":
                for coluna in tabela.primary_key.columns:
                    if coluna.autoincrement:
                        sequencias_oracle.append(
                            (
                                tabela.name,
                                coluna.name,
                                max(linha[coluna.name] for linha in linhas),
                            )
                        )
    if engine.dialect.name == "oracle":
        with engine.connect() as conexao:
            for nome_tabela, nome_coluna, valor_maximo in sequencias_oracle:
                _reiniciar_sequencia(
                    conexao,
                    engine.dialect.name,
                    nome_tabela,
                    nome_coluna,
                    valor_maximo,
                )


def restaurar_backup(arquivo_origem):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    arquivo_temporario = None
    staging = Path(tempfile.mkdtemp(prefix=".backup-restore-", dir=DATA_DIR))
    with _backup_lock:
        try:
            total = 0
            with tempfile.NamedTemporaryFile(
                dir=DATA_DIR, prefix=".backup-upload-", suffix=".zip", delete=False
            ) as temporario:
                arquivo_temporario = Path(temporario.name)
                while True:
                    bloco = arquivo_origem.read(1024 * 1024)
                    if not bloco:
                        break
                    total += len(bloco)
                    if total > MAX_UPLOAD_SIZE:
                        raise ValueError("O arquivo excede o limite de 2 GB.")
                    temporario.write(bloco)
            try:
                arquivo_zip = zipfile.ZipFile(arquivo_temporario)
            except zipfile.BadZipFile as exc:
                raise ValueError("O arquivo enviado não é um ZIP válido.") from exc
            with arquivo_zip:
                membros = _validar_membros(arquivo_zip)
                erro_crc = arquivo_zip.testzip()
                if erro_crc:
                    raise ValueError("O backup está corrompido.")
                snapshot = _validar_snapshot(arquivo_zip, membros)
                raiz_staging = staging.resolve()
                arquivos_staging = []
                for nome, info in membros.items():
                    caminho = PurePosixPath(nome)
                    if caminho.parts[0] != "files":
                        continue
                    relativo = Path(*caminho.parts[1:])
                    destino = (staging / relativo).resolve()
                    if not destino.is_relative_to(raiz_staging):
                        raise ValueError("O backup contém um caminho inseguro.")
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    with arquivo_zip.open(info) as origem, destino.open("wb") as saida:
                        shutil.copyfileobj(origem, saida)
                    arquivos_staging.append((destino, relativo))
            _restaurar_tabelas(snapshot)
            for origem, relativo in arquivos_staging:
                if relativo.as_posix() in ("database.json", "backup_settings.json"):
                    continue
                destino = DATA_DIR / relativo
                destino.parent.mkdir(parents=True, exist_ok=True)
                os.replace(origem, destino)
        finally:
            if arquivo_temporario and arquivo_temporario.exists():
                arquivo_temporario.unlink()
            shutil.rmtree(staging, ignore_errors=True)


def _deve_executar_agora(configuracao, agora):
    if not configuracao["enabled"] or agora.strftime("%H:%M") != configuracao["time"]:
        return False
    if configuracao["period"] == "weekly" and agora.weekday() != configuracao["weekday"]:
        return False
    return configuracao["last_run"] != agora.date().isoformat()


async def executar_agendador_backup():
    ultima_tentativa = None
    while True:
        try:
            agora = datetime.now()
            configuracao = obter_configuracao()
            data_atual = agora.date().isoformat()
            if (
                data_atual != ultima_tentativa
                and _deve_executar_agora(configuracao, agora)
            ):
                ultima_tentativa = data_atual
                await asyncio.to_thread(criar_backup)
                salvar_configuracao({"last_run": agora.date().isoformat()})
        except Exception as erro:
            logger.exception("Erro no backup automático: %s", erro)
        await asyncio.sleep(30)
