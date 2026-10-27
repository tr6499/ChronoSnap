#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Execute este instalador com privilégios administrativos."
    exit 1
fi
if [ "$#" -ne 1 ]; then
    echo "Informe a pasta de dados do ChronoSnap."
    exit 1
fi

data_dir=$1
config_file="$data_dir/database.json"
configuracao_existente=0
if [ -e "$config_file" ] &&
    ! grep -Eq '"backend"[[:space:]]*:[[:space:]]*"sqlite"' "$config_file"; then
    configuracao_existente=1
fi

if command -v systemctl >/dev/null 2>&1 &&
    systemctl is-active --quiet postgresql; then
    echo "PostgreSQL já está em execução. Configure a conexão na página Banco de dados."
    exit 0
fi

if command -v psql >/dev/null 2>&1 &&
    command -v systemctl >/dev/null 2>&1 &&
    systemctl list-unit-files --type=service --no-legend 'postgresql*' |
        grep -q .; then
    systemctl enable --now postgresql
    echo "PostgreSQL existente iniciado. Configure a conexão na página Banco de dados."
    exit 0
fi

inicializar_cluster_pgsql() {
    diretorio_dados=$1
    if [ -s "$diretorio_dados/PG_VERSION" ]; then
        return
    fi
    if command -v postgresql-setup >/dev/null 2>&1; then
        postgresql-setup --initdb
    elif command -v initdb >/dev/null 2>&1; then
        install -d -o postgres -g postgres "$diretorio_dados"
        runuser -u postgres -- initdb -D "$diretorio_dados"
    else
        echo "Não foi encontrado o utilitário para inicializar o PostgreSQL."
        exit 1
    fi
}

if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y postgresql postgresql-client
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y postgresql-server
    inicializar_cluster_pgsql /var/lib/pgsql/data
elif command -v yum >/dev/null 2>&1; then
    yum install -y postgresql-server
    inicializar_cluster_pgsql /var/lib/pgsql/data
elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive refresh
    zypper --non-interactive install postgresql-server postgresql-contrib
    inicializar_cluster_pgsql /var/lib/pgsql/data
elif command -v pacman >/dev/null 2>&1; then
    pacman -S --noconfirm postgresql
    if [ ! -s /var/lib/postgres/data/PG_VERSION ]; then
        install -d -o postgres -g postgres /var/lib/postgres/data
        su -s /bin/sh postgres -c "initdb -D /var/lib/postgres/data"
    fi
else
    echo "Distribuição Linux não suportada para instalação automática do PostgreSQL."
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemd não encontrado. Inicie o serviço PostgreSQL manualmente."
    exit 1
fi
systemctl enable --now postgresql

if [ "$configuracao_existente" -eq 1 ]; then
    echo "PostgreSQL instalado. A configuração existente do ChronoSnap foi preservada."
    exit 0
fi

app_password=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
sql_file=$(mktemp)
config_temp=
trap 'rm -f "$sql_file" ${config_temp:+"$config_temp"}' EXIT HUP INT TERM
chmod 600 "$sql_file"
cat > "$sql_file" <<SQL
CREATE ROLE chronosnap_app LOGIN PASSWORD '$app_password';
CREATE DATABASE chronosnap OWNER chronosnap_app;
SQL
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -d postgres -f "$sql_file" >/dev/null

uid=${PKEXEC_UID:-${SUDO_UID:-0}}
gid=${PKEXEC_GID:-${SUDO_GID:-}}
[ -n "$gid" ] || gid=$(id -g "$uid")
mkdir -p "$data_dir"
config_temp=$(mktemp "$data_dir/.database.XXXXXX")
cat > "$config_temp" <<JSON
{
  "backend": "postgresql",
  "host": "localhost",
  "port": 5432,
  "database": "chronosnap",
  "username": "chronosnap_app",
  "password": "$app_password"
}
JSON
chown "$uid:$gid" "$config_temp"
chmod 600 "$config_temp"
if [ -e "$config_file" ]; then
    echo "A configuração do ChronoSnap mudou durante a instalação; o arquivo foi preservado."
    exit 1
fi
mv "$config_temp" "$config_file"
config_temp=
echo "PostgreSQL instalado e configurado para o ChronoSnap."
