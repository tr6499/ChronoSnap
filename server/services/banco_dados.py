import os
from pathlib import Path

from sqlalchemy import Integer, MetaData, Table, func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from database import (
    DATABASE_CONFIG,
    PROVEDORES,
    SQLITE_DATABASE_FILE,
    Base,
    carregar_configuracao_banco,
    criar_engine,
    engine,
)
import models  # noqa: F401  registra as tabelas em Base.metadata
import models_usuarios  # noqa: F401

SUGESTAO_BANCO = "chronosnap"
TABELAS_PADRAO_INICIAIS = {
    "usuarios_sistema",
    "configuracoes_sistema",
    "logs_auditoria",
}
SUGESTAO_USUARIO = "chronosnap_app"


def nome_provedor(backend):
    if backend == "sqlite":
        return "SQLite"
    return PROVEDORES[backend]["nome"]


def configuracao_publica(configuracao=None):
    configuracao = configuracao or DATABASE_CONFIG
    backend = configuracao["backend"]
    if backend == "sqlite":
        return {
            "backend": "sqlite",
            "tipo": "SQLite",
            "local": str(SQLITE_DATABASE_FILE),
        }
    return {
        "backend": backend,
        "tipo": nome_provedor(backend),
        "local": (
            f'{configuracao["host"]}:{configuracao["port"]}/'
            f'{configuracao["database"]}'
        ),
    }


ADMINISTRADOR_PADRAO = {
    "postgresql": "postgres",
    "mysql": "root",
    "mariadb": "root",
    "mssql": "sa",
    "oracle": "system",
}


def provedores_disponiveis():
    return [
        {
            "backend": backend,
            "nome": dados["nome"],
            "porta": dados["porta"],
            "rotulo_banco": dados["rotulo_banco"],
            "migracao": bool(dados.get("migracao")),
            "administrador": ADMINISTRADOR_PADRAO[backend],
            "cria_banco": backend != "oracle",
        }
        for backend, dados in PROVEDORES.items()
    ]


def conexoes_sugeridas():
    """Valores iniciais de cada provedor; a senha salva nunca é devolvida."""
    salva = carregar_configuracao_banco()
    sugeridas = {}
    for backend, dados in PROVEDORES.items():
        valores = {
            "host": "localhost",
            "port": dados["porta"],
            "database": SUGESTAO_BANCO,
            "username": SUGESTAO_USUARIO,
            "salva": False,
        }
        if salva["backend"] == backend:
            valores.update(
                host=salva["host"],
                port=salva["port"],
                database=salva["database"],
                username=salva["username"],
                salva=True,
            )
        sugeridas[backend] = valores
    return sugeridas


def informacoes_servidor():
    """Versão e tamanho do banco em uso; falhas não impedem a página."""
    informacoes = {"versao": None, "tamanho": None}
    try:
        informacoes["versao"] = ".".join(
            str(parte) for parte in engine.dialect.server_version_info or ()
        ) or None
    except (AttributeError, TypeError):
        pass
    if engine.dialect.name == "postgresql":
        try:
            with engine.connect() as conexao:
                informacoes["tamanho"] = conexao.execute(
                    text("SELECT pg_database_size(current_database())")
                ).scalar_one()
        except SQLAlchemyError:
            pass
    return informacoes


def detectar_postgresql_local():
    """Pastas de instalações PostgreSQL locais conhecidas."""
    instalacoes = []
    if os.name == "nt":
        raiz = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        base = raiz / "PostgreSQL"
        if base.is_dir():
            for versao in sorted(base.iterdir(), reverse=True):
                if (versao / "bin" / "psql.exe").is_file():
                    instalacoes.append(
                        {
                            "versao": versao.name,
                            "programa": str(versao),
                            "dados": str(versao / "data"),
                        }
                    )
    else:
        for base in (Path("/usr/lib/postgresql"), Path("/usr/pgsql")):
            if base.is_dir():
                for versao in sorted(base.iterdir(), reverse=True):
                    if (versao / "bin" / "psql").is_file():
                        instalacoes.append(
                            {
                                "versao": versao.name,
                                "programa": str(versao),
                                "dados": f"/var/lib/postgresql/{versao.name}",
                            }
                        )
    return instalacoes


def _detalhe_erro(exc):
    origem = getattr(exc, "orig", None) or exc
    linhas = [linha.strip() for linha in str(origem).splitlines() if linha.strip()]
    return linhas[0][:300] if linhas else origem.__class__.__name__


def _criar_engine_teste(configuracao):
    try:
        return criar_engine(configuracao)
    except ImportError as exc:
        raise ConnectionError(
            "O driver deste banco não está incluído nesta instalação."
        ) from exc


def testar_conexao(configuracao):
    nome = nome_provedor(configuracao["backend"])
    teste_engine = _criar_engine_teste(configuracao)
    try:
        with teste_engine.connect() as conexao:
            conexao.execute(text("SELECT 1" if configuracao["backend"] != "oracle" else "SELECT 1 FROM DUAL"))
    except SQLAlchemyError as exc:
        detalhe = _detalhe_erro(exc)
        dica = ""
        if "no password supplied" in detalhe:
            dica = " Dica: informe a senha do usuário."
        elif "senha falhou" in detalhe or "password authentication" in detalhe:
            dica = (
                " Dica: o usuário não existe neste servidor ou a senha está "
                "diferente. Para criá-lo, escolha “Criar automaticamente” e "
                "informe a senha do administrador (postgres)."
            )
        raise ConnectionError(
            f"Não foi possível conectar ao {nome}. Confira servidor, porta, "
            f"banco, usuário e senha. Detalhe: {detalhe}{dica}"
        ) from exc
    finally:
        teste_engine.dispose()


def criar_tabelas(configuracao):
    """Cria apenas as tabelas ausentes; nunca altera ou apaga dados."""
    novo_engine = _criar_engine_teste(configuracao)
    try:
        Base.metadata.create_all(bind=novo_engine)
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "A conexão funcionou, mas não foi possível criar as tabelas. "
            "O usuário precisa de permissão para criar tabelas e índices. "
            f"Detalhe: {_detalhe_erro(exc)}"
        ) from exc
    finally:
        novo_engine.dispose()


def provisionar_postgresql(administrador, destino):
    """Cria usuário e banco exclusivos usando credenciais administrativas
    informadas apenas nesta chamada."""
    import psycopg
    from psycopg import sql

    usuario = destino["username"]
    banco = destino["database"]
    try:
        with psycopg.connect(
            host=administrador["host"],
            port=administrador["port"],
            dbname="postgres",
            user=administrador["username"],
            password=administrador["password"],
            connect_timeout=10,
            autocommit=True,
        ) as conexao:
            if conexao.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (usuario,)
            ).fetchone():
                raise ValueError(
                    f"O usuário “{usuario}” já existe no servidor. Escolha "
                    "outro nome ou use a opção de banco já criado."
                )
            if conexao.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (banco,)
            ).fetchone():
                raise ValueError(
                    f"O banco “{banco}” já existe no servidor. Escolha outro "
                    "nome ou use a opção de banco já criado."
                )
            conexao.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(usuario), sql.Literal(destino["password"])
                )
            )
            conexao.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(banco), sql.Identifier(usuario)
                )
            )
    except psycopg.Error as exc:
        raise ConnectionError(
            "Não foi possível criar o usuário e o banco com a conta "
            f"administrativa informada. Detalhe: {_detalhe_erro(exc)}"
        ) from exc


def _erro_provisionamento(exc):
    return ConnectionError(
        "Não foi possível criar o usuário e o banco com a conta "
        f"administrativa informada. Detalhe: {_detalhe_erro(exc)}"
    )


def _provisionar_mysql(administrador, destino):
    import pymysql

    usuario = destino["username"]
    banco = destino["database"]
    try:
        conexao = pymysql.connect(
            host=administrador["host"],
            port=administrador["port"],
            user=administrador["username"],
            password=administrador["password"],
            connect_timeout=10,
            autocommit=True,
        )
    except pymysql.Error as exc:
        raise _erro_provisionamento(exc) from exc
    try:
        with conexao.cursor() as cursor:
            cursor.execute("SELECT 1 FROM mysql.user WHERE User = %s", (usuario,))
            if cursor.fetchone():
                raise ValueError(
                    f"O usuário “{usuario}” já existe no servidor. Escolha "
                    "outro nome ou use a opção de banco já criado."
                )
            cursor.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s",
                (banco,),
            )
            if cursor.fetchone():
                raise ValueError(
                    f"O banco “{banco}” já existe no servidor. Escolha outro "
                    "nome ou use a opção de banco já criado."
                )
            identificador = "`" + banco.replace("`", "``") + "`"
            cursor.execute(
                f"CREATE DATABASE {identificador} CHARACTER SET utf8mb4"
            )
            cursor.execute(
                "CREATE USER %s@'%%' IDENTIFIED BY %s",
                (usuario, destino["password"]),
            )
            cursor.execute(
                f"GRANT ALL PRIVILEGES ON {identificador}.* TO %s@'%%'",
                (usuario,),
            )
    except pymysql.Error as exc:
        raise _erro_provisionamento(exc) from exc
    finally:
        conexao.close()


def _provisionar_mssql(administrador, destino):
    import pymssql

    usuario = destino["username"]
    banco = destino["database"]
    ident = lambda valor: "[" + valor.replace("]", "]]") + "]"  # noqa: E731
    literal = lambda valor: "N'" + valor.replace("'", "''") + "'"  # noqa: E731
    try:
        conexao = pymssql.connect(
            server=administrador["host"],
            port=administrador["port"],
            user=administrador["username"],
            password=administrador["password"],
            login_timeout=10,
            autocommit=True,
        )
    except pymssql.Error as exc:
        raise _erro_provisionamento(exc) from exc
    try:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT 1 FROM sys.server_principals WHERE name = %s", (usuario,)
        )
        if cursor.fetchone():
            raise ValueError(
                f"O login “{usuario}” já existe no servidor. Escolha outro "
                "nome ou use a opção de banco já criado."
            )
        cursor.execute("SELECT 1 FROM sys.databases WHERE name = %s", (banco,))
        if cursor.fetchone():
            raise ValueError(
                f"O banco “{banco}” já existe no servidor. Escolha outro "
                "nome ou use a opção de banco já criado."
            )
        cursor.execute(f"CREATE DATABASE {ident(banco)}")
        cursor.execute(
            f"CREATE LOGIN {ident(usuario)} WITH PASSWORD = "
            f"{literal(destino['password'])}, CHECK_POLICY = OFF"
        )
        cursor.execute(f"USE {ident(banco)}")
        cursor.execute(f"CREATE USER {ident(usuario)} FOR LOGIN {ident(usuario)}")
        cursor.execute(f"ALTER ROLE db_owner ADD MEMBER {ident(usuario)}")
    except pymssql.Error as exc:
        raise _erro_provisionamento(exc) from exc
    finally:
        conexao.close()


def _provisionar_oracle(administrador, destino):
    import oracledb

    usuario = destino["username"].upper()
    senha = destino["password"]
    if '"' in senha:
        raise ValueError("A senha para Oracle não pode conter aspas duplas.")
    if '"' in usuario:
        raise ValueError("O nome de usuário não pode conter aspas duplas.")
    try:
        conexao = oracledb.connect(
            user=administrador["username"],
            password=administrador["password"],
            host=administrador["host"],
            port=administrador["port"],
            service_name=destino["database"],
            tcp_connect_timeout=10,
        )
    except oracledb.Error as exc:
        raise _erro_provisionamento(exc) from exc
    try:
        with conexao.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM dba_users WHERE username = :1", [usuario]
            )
            if cursor.fetchone():
                raise ValueError(
                    f"O usuário “{usuario}” já existe no servidor. Escolha "
                    "outro nome ou use a opção de banco já criado."
                )
            cursor.execute(f'CREATE USER "{usuario}" IDENTIFIED BY "{senha}"')
            cursor.execute(
                f'GRANT CREATE SESSION, CREATE TABLE, CREATE SEQUENCE, '
                f'CREATE VIEW, UNLIMITED TABLESPACE TO "{usuario}"'
            )
    except oracledb.Error as exc:
        raise _erro_provisionamento(exc) from exc
    finally:
        conexao.close()


def provisionar_banco(administrador, destino):
    """Cria usuário (e banco, quando o servidor tem esse conceito) com
    credenciais administrativas usadas somente nesta chamada."""
    backend = destino["backend"]
    try:
        if backend == "postgresql":
            provisionar_postgresql(administrador, destino)
        elif backend in ("mysql", "mariadb"):
            _provisionar_mysql(administrador, destino)
        elif backend == "mssql":
            _provisionar_mssql(administrador, destino)
        elif backend == "oracle":
            _provisionar_oracle(administrador, destino)
        else:
            raise ValueError("Provedor inválido.")
    except ImportError as exc:
        raise ConnectionError(
            "O driver deste banco não está incluído nesta instalação."
        ) from exc


def _reiniciar_sequencia(conexao, backend, tabela, coluna, valor_maximo):
    """Ajusta o próximo id gerado após a cópia com ids explícitos.

    MySQL, MariaDB e SQL Server já avançam o contador sozinhos."""
    if backend == "postgresql":
        conexao.execute(
            text(
                "SELECT setval(CAST(pg_get_serial_sequence("
                ":nome_tabela, :nome_coluna) AS regclass), :valor, true)"
            ),
            {"nome_tabela": tabela, "nome_coluna": coluna, "valor": valor_maximo},
        )
    elif backend == "oracle":
        conexao.execute(
            text(
                f'ALTER TABLE "{tabela}" MODIFY "{coluna}" '
                "GENERATED BY DEFAULT ON NULL AS IDENTITY (START WITH LIMIT VALUE)"
            )
        )


def migrar_sqlite(configuracao):
    backend = configuracao["backend"]
    if backend not in PROVEDORES or not PROVEDORES[backend].get("migracao"):
        raise ValueError("A migração de dados não está disponível para este banco.")
    nome = nome_provedor(backend)
    if not SQLITE_DATABASE_FILE.is_file():
        raise ValueError("O arquivo SQLite de origem não foi encontrado.")

    destino = _criar_engine_teste(configuracao)
    origem = criar_engine({"backend": "sqlite"})
    try:
        origem_tabelas = set(inspect(origem).get_table_names())
        tabelas_modelo = Base.metadata.sorted_tables
        with destino.connect() as conexao_destino:
            tabelas_destino = set(inspect(conexao_destino).get_table_names())
            tabelas_compartilhadas = (
                tabelas_destino & set(Base.metadata.tables)
            )
            tabelas_padrao_presentes = []
            for nome_tabela in tabelas_compartilhadas:
                tem_registros = conexao_destino.execute(
                    select(1)
                    .select_from(Base.metadata.tables[nome_tabela])
                    .limit(1)
                ).first()
                if not tem_registros:
                    continue
                if nome_tabela in TABELAS_PADRAO_INICIAIS:
                    tabelas_padrao_presentes.append(nome_tabela)
                    continue
                raise ValueError(
                    f"O banco {nome} de destino já contém dados do "
                    "ChronoSnap. Use um banco vazio para migrar."
                )

        reinicios = []
        with origem.connect() as conexao_origem:
            conexao_origem.exec_driver_sql("BEGIN IMMEDIATE")
            with destino.begin() as conexao_destino:
                Base.metadata.create_all(bind=conexao_destino)
                # Usuário, configurações e auditoria criados na primeira
                # inicialização são substituídos pelos do SQLite.
                for tabela in reversed(tabelas_modelo):
                    if tabela.name in tabelas_padrao_presentes:
                        conexao_destino.execute(tabela.delete())
                for tabela in tabelas_modelo:
                    if tabela.name not in origem_tabelas:
                        continue
                    tabela_origem = Table(
                        tabela.name,
                        MetaData(),
                        autoload_with=conexao_origem,
                    )
                    colunas_compartilhadas = [
                        coluna.name
                        for coluna in tabela.columns
                        if coluna.name in tabela_origem.c
                    ]
                    quantidade_origem = conexao_origem.execute(
                        select(func.count()).select_from(tabela_origem)
                    ).scalar_one()
                    resultado = conexao_origem.execute(
                        select(
                            *[
                                tabela_origem.c[nome_coluna]
                                for nome_coluna in colunas_compartilhadas
                            ]
                        )
                    )
                    while lote := resultado.mappings().fetchmany(500):
                        conexao_destino.execute(
                            tabela.insert(),
                            [
                                {
                                    nome_coluna: registro[nome_coluna]
                                    for nome_coluna in colunas_compartilhadas
                                }
                                for registro in lote
                            ],
                        )
                    quantidade_destino = conexao_destino.execute(
                        select(func.count()).select_from(tabela)
                    ).scalar_one()
                    if quantidade_destino != quantidade_origem:
                        raise RuntimeError(
                            f"A contagem de registros da tabela {tabela.name} "
                            "não corresponde após a cópia."
                        )
                    coluna_chave = next(
                        (
                            coluna
                            for coluna in tabela.primary_key.columns
                            if coluna.primary_key
                            and isinstance(coluna.type, Integer)
                        ),
                        None,
                    )
                    if (
                        coluna_chave is not None
                        and coluna_chave.name in colunas_compartilhadas
                    ):
                        valor_maximo = conexao_destino.execute(
                            select(func.max(coluna_chave))
                        ).scalar_one()
                        if valor_maximo is not None:
                            if backend == "oracle":
                                # DDL do Oracle confirma a transação; é
                                # feito somente após a cópia completa.
                                reinicios.append(
                                    (tabela.name, coluna_chave.name, valor_maximo)
                                )
                            else:
                                _reiniciar_sequencia(
                                    conexao_destino,
                                    backend,
                                    tabela.name,
                                    coluna_chave.name,
                                    valor_maximo,
                                )
            for tabela_nome, coluna_nome, valor in reinicios:
                with destino.begin() as conexao_destino:
                    _reiniciar_sequencia(
                        conexao_destino, backend, tabela_nome, coluna_nome, valor
                    )
            conexao_origem.commit()
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "A migração falhou. O SQLite original foi preservado e o banco "
            f"{nome} não foi ativado. Detalhe: {_detalhe_erro(exc)}"
        ) from exc
    finally:
        origem.dispose()
        destino.dispose()


migrar_sqlite_para_postgresql = migrar_sqlite
