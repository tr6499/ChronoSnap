import asyncio
import calendar
from datetime import datetime

from database import SessionLocal, engine
from models import MarcacaoAFD
from models_usuarios import ConfiguracaoSistema

CHAVE_VALOR = "banco_retencao_valor"
CHAVE_UNIDADE = "banco_retencao_unidade"
UNIDADES = ("dias", "meses", "anos")
INTERVALO_VERIFICACAO_SEGUNDOS = 3600


def _ler(db, chave):
    item = db.query(ConfiguracaoSistema).filter(
        ConfiguracaoSistema.chave == chave
    ).first()
    return item.valor if item else None


def _gravar(db, chave, valor, descricao):
    item = db.query(ConfiguracaoSistema).filter(
        ConfiguracaoSistema.chave == chave
    ).first()
    if item:
        item.valor = str(valor)
    else:
        db.add(ConfiguracaoSistema(chave=chave, valor=str(valor), descricao=descricao))


def obter_retencao_banco(db):
    """Retorna (valor, unidade). valor 0 significa retenção desativada."""
    try:
        valor = int(_ler(db, CHAVE_VALOR) or 0)
    except ValueError:
        valor = 0
    unidade = _ler(db, CHAVE_UNIDADE)
    if unidade not in UNIDADES:
        unidade = "dias"
    return max(valor, 0), unidade


def salvar_retencao_banco(db, valor, unidade):
    _gravar(db, CHAVE_VALOR, valor, "Período máximo de retenção das marcações")
    _gravar(db, CHAVE_UNIDADE, unidade, "Unidade do período de retenção (dias, meses, anos)")
    db.commit()


def _subtrair_meses(data, meses):
    indice = data.year * 12 + (data.month - 1) - meses
    ano, mes = divmod(indice, 12)
    mes += 1
    dia = min(data.day, calendar.monthrange(ano, mes)[1])
    return data.replace(year=ano, month=mes, day=dia)


def calcular_data_corte(valor, unidade, agora=None):
    agora = agora or datetime.now()
    if unidade == "dias":
        from datetime import timedelta
        return agora - timedelta(days=valor)
    if unidade == "meses":
        return _subtrair_meses(agora, valor)
    return _subtrair_meses(agora, valor * 12)


def compactar_banco():
    """Compacta o arquivo SQLite e recupera espaço em disco."""
    with engine.connect() as conexao:
        conexao.execution_options(
            isolation_level="AUTOCOMMIT"
        ).exec_driver_sql("VACUUM")


def aplicar_retencao_banco(db=None):
    """Remove marcações mais antigas que o período configurado."""
    sessao = db or SessionLocal()
    try:
        valor, unidade = obter_retencao_banco(sessao)
        if valor <= 0:
            return 0
        corte = calcular_data_corte(valor, unidade)
        removidos = sessao.query(MarcacaoAFD).filter(
            MarcacaoAFD.data_hora < corte
        ).delete(synchronize_session=False)
        sessao.commit()
        return removidos
    finally:
        if db is None:
            sessao.close()


async def executar_retencao_banco():
    while True:
        try:
            await asyncio.to_thread(aplicar_retencao_banco)
        except Exception as erro:
            print(f"Erro na retenção do banco: {erro}")
        await asyncio.sleep(INTERVALO_VERIFICACAO_SEGUNDOS)
