"""Diretórios de dados do ChronoSnap."""
import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
_data = os.environ.get("CHRONOSNAP_DATA")

if _data:
    DATA_DIR = Path(_data)
    DB_DIR = DATA_DIR / "banco"
    LOGS_DIR = DATA_DIR / "logs"
    DOWNLOADS_DIR = DATA_DIR / "downloads"
else:
    DATA_DIR = APP_DIR.parent
    DB_DIR = DATA_DIR / "banco"
    LOGS_DIR = APP_DIR / "logs"
    DOWNLOADS_DIR = APP_DIR / "downloads"

for _d in (DATA_DIR, DB_DIR, LOGS_DIR, DOWNLOADS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
