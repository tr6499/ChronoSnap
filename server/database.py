import json
import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app_paths import DATA_DIR, DB_DIR as BANCO_DIR

DATABASE_CONFIG_FILE = DATA_DIR / "database.json"
SQLITE_DATABASE_FILE = BANCO_DIR / "afd.db"


PROVEDORES = {
    "postgresql": {
        "nome": "PostgreSQL",
        "driver": "postgresql+psycopg",
        "porta": 5432,
        "conexao": {"connect_timeout": 10},
        "rotulo_banco": "Banco de dados",
        "migracao": True,
    },
    "mysql": {
        "nome": "MySQL",
        "driver": "mysql+pymysql",
        "porta": 3306,
        "conexao": {"connect_timeout": 10},
        "rotulo_banco": "Banco de dados",
        "consulta": {"charset": "utf8mb4"},
        "migracao": True,
    },
    "mariadb": {
        "nome": "MariaDB",
        "driver": "mariadb+pymysql",
        "porta": 3306,
        "conexao": {"connect_timeout": 10},
        "rotulo_banco": "Banco de dados",
        "consulta": {"charset": "utf8mb4"},
        "migracao": True,
    },
    "mssql": {
        "nome": "SQL Server",
        "driver": "mssql+pymssql",
        "porta": 1433,
        "conexao": {"login_timeout": 10},
        "rotulo_banco": "Banco de dados",
        "consulta": {"charset": "utf8"},
        "migracao": True,
    },
    "oracle": {
        "nome": "Oracle",
        "driver": "oracle+oracledb",
        "porta": 1521,
        "conexao": {"tcp_connect_timeout": 10},
        "rotulo_banco": "Service name",
        "migracao": True,
    },
}


def _normalizar_configuracao(configuracao):
    if not isinstance(configuracao, dict):
        raise ValueError("A configuração do banco deve ser um objeto.")
    backend = configuracao.get("backend", "sqlite")
    if backend == "sqlite":
        return {"backend": "sqlite"}
    if backend not in PROVEDORES:
        raise ValueError("Tipo de banco de dados inválido.")
    nome = PROVEDORES[backend]["nome"]

    host = configuracao.get("host", "")
    database = configuracao.get("database", "")
    username = configuracao.get("username", "")
    password = configuracao.get("password", "")
    if not all(
        isinstance(valor, str)
        for valor in (host, database, username, password)
    ):
        raise ValueError(f"Os dados de conexão {nome} são inválidos.")
    host, database, username = (
        valor.strip() for valor in (host, database, username)
    )
    valor_porta = configuracao.get("port", PROVEDORES[backend]["porta"])
    if isinstance(valor_porta, bool):
        raise ValueError(f"A porta do {nome} deve ser um número.")
    try:
        port = int(valor_porta)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"A porta do {nome} deve ser um número.") from exc
    if not host or not database or not username:
        raise ValueError(
            f"Informe servidor, banco de dados e usuário {nome}."
        )
    if not 1 <= port <= 65535:
        raise ValueError("A porta deve estar entre 1 e 65535.")
    return {
        "backend": backend,
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password": password,
    }


normalizar_configuracao = _normalizar_configuracao


def carregar_configuracao_banco():
    try:
        dados = json.loads(DATABASE_CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"backend": "sqlite"}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Não foi possível ler {DATABASE_CONFIG_FILE}: {exc}"
        ) from exc
    try:
        return _normalizar_configuracao(dados)
    except ValueError as exc:
        raise RuntimeError(f"Configuração do banco inválida: {exc}") from exc


def salvar_configuracao_banco(configuracao):
    dados = _normalizar_configuracao(configuracao)
    DATABASE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATABASE_CONFIG_FILE.parent,
            prefix=".database-",
            suffix=".tmp",
            delete=False,
        ) as arquivo:
            temporario = Path(arquivo.name)
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        if os.name == "nt":
            usuario = subprocess.run(
                ["whoami"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.strip()
            subprocess.run(
                [
                    "icacls",
                    str(temporario),
                    "/inheritance:r",
                    "/grant:r",
                    f"{usuario}:(F)",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        else:
            temporario.chmod(0o600)
        os.replace(temporario, DATABASE_CONFIG_FILE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"Não foi possível salvar a configuração protegida do banco: {exc}"
        ) from exc
    finally:
        if temporario and temporario.exists():
            temporario.unlink()
    return dados


def criar_engine(configuracao):
    configuracao = _normalizar_configuracao(configuracao)
    if configuracao["backend"] == "sqlite":
        novo_engine = create_engine(
            URL.create("sqlite", database=str(SQLITE_DATABASE_FILE)),
            connect_args={"check_same_thread": False, "timeout": 60},
        )

        @event.listens_for(novo_engine, "connect")
        def ativar_wal_sqlite(conexao, registro):
            cursor = conexao.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()

        return novo_engine

    provedor = PROVEDORES[configuracao["backend"]]
    consulta = dict(provedor.get("consulta", {}))
    if configuracao["backend"] == "oracle":
        consulta["service_name"] = configuracao["database"]
        configuracao = {**configuracao, "database": None}
    return create_engine(
        URL.create(
            provedor["driver"],
            query=consulta,
            username=configuracao["username"],
            password=configuracao["password"],
            host=configuracao["host"],
            port=configuracao["port"],
            database=configuracao["database"],
        ),
        pool_pre_ping=True,
        connect_args=provedor.get("conexao", {}),
    )


DATABASE_CONFIG = carregar_configuracao_banco()
engine = criar_engine(DATABASE_CONFIG)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()
