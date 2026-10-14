from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

BANCO_DIR = BASE_DIR / "banco"
BANCO_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite:///{BANCO_DIR / 'afd.db'}"


engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False
    }
)


@event.listens_for(engine, "connect")
def ativar_wal_sqlite(conexao, registro):
    cursor = conexao.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


Base = declarative_base()