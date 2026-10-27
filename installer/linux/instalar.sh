#!/bin/sh
# Inicia o instalador visual do ChronoSnap (instala python3-tk se necessário).
cd "$(dirname "$0")" || exit 1

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "Instalando suporte gráfico (tkinter)..."
    if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
    if command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update && $SUDO apt-get install -y python3 python3-tk
    elif command -v dnf >/dev/null 2>&1; then $SUDO dnf install -y python3 python3-tkinter
    elif command -v yum >/dev/null 2>&1; then $SUDO yum install -y python3 python3-tkinter
    elif command -v pacman >/dev/null 2>&1; then $SUDO pacman -S --noconfirm python tk
    elif command -v zypper >/dev/null 2>&1; then $SUDO zypper install -y python3 python3-tk
    else echo "Instale python3 e tkinter manualmente."; exit 1
    fi
fi

exec python3 installer.py
