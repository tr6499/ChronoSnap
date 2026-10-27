"""Ponto de entrada do servidor (usado na versão compilada)."""
import argparse
import os
import sys
from pathlib import Path

if "CHRONOSNAP_DATA" not in os.environ and "__compiled__" in globals():
    os.environ["CHRONOSNAP_DATA"] = str(Path(sys.argv[0]).resolve().parent.parent / "data")

import app_paths  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if _s is not None:
        _s.reconfigure(encoding="utf-8", errors="replace")

# Caminhos relativos (ex.: "downloads") passam a apontar para a pasta de dados
os.chdir(app_paths.DATA_DIR)

import uvicorn  # noqa: E402

from app import app  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_config=None)


if __name__ == "__main__":
    main()
