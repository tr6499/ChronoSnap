#!/bin/sh
# Gera o pacote Linux (código compilado com Nuitka). Execute em Linux x86_64.
# Requisitos: python3 (com tkinter e venv), gcc, patchelf, make.
#   Debian/Ubuntu: sudo apt install python3-venv python3-tk python3-dev gcc patchelf
set -e
VERSION="${1:-1.0.5}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/build/work_linux"
OUT="$ROOT/build/out"
PKG="$WORK/ChronoSnap-linux"

[ -x "$WORK/venv/bin/python" ] || python3 -m venv "$WORK/venv"
PY="$WORK/venv/bin/python"
"$PY" -m pip install -q -r "$ROOT/server/requirements.txt" nuitka zstandard ordered-set

rm -rf "$PKG"; mkdir -p "$PKG/payload" "$OUT"
COMMON="--standalone --assume-yes-for-downloads --remove-output --product-name=ChronoSnap --file-version=$VERSION.0 --product-version=$VERSION.0"

export PYTHONPATH="$ROOT/server"
"$PY" -m nuitka $COMMON --output-dir="$WORK/nk_server" --output-filename=ChronoSnapServer \
    --include-data-dir="$ROOT/server/templates=templates" --include-data-dir="$ROOT/server/static=static" \
    --include-package=uvicorn --include-package=routes --include-package=services \
    --include-package=sqlalchemy.dialects.sqlite --include-package=sqlalchemy.dialects.postgresql \
    --include-package=sqlalchemy.dialects.mysql --include-package=sqlalchemy.dialects.mssql \
    --include-package=sqlalchemy.dialects.oracle \
    --include-package=psycopg --include-package=psycopg_binary --include-package=aiosqlite \
    --include-package=pymysql --include-package=pymssql --include-package=oracledb \
    --include-module=python_multipart --include-module=bcrypt "$ROOT/server/run_server.py"
mv "$WORK/nk_server/run_server.dist" "$PKG/payload/server"

"$PY" -m nuitka $COMMON --output-dir="$WORK/nk_manager" --output-filename=ChronoSnapManager \
    --enable-plugin=tk-inter --include-package=pystray --include-package=PIL \
    "$ROOT/installer/manager.py"
mv "$WORK/nk_manager/manager.dist" "$PKG/payload/manager"

cp "$ROOT/COPYING" "$PKG/payload/LICENSE.txt"
cp "$ROOT/installer/linux/installer.py" "$ROOT/installer/linux/instalar.sh" \
    "$ROOT/installer/linux/install_postgresql.sh" "$PKG/"
chmod +x "$PKG/instalar.sh" "$PKG/install_postgresql.sh"
tar -C "$WORK" -czf "$OUT/ChronoSnap-linux-x64-$VERSION.tar.gz" ChronoSnap-linux
echo "Pacote gerado em $OUT/ChronoSnap-linux-x64-$VERSION.tar.gz"
