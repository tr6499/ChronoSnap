import hashlib
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func

from models import MarcacaoAFD


def assinatura_marcacao(loja_id, registro):
    partes = (
        str(loja_id),
        str(registro.get("nsr") or "").strip(),
        str(registro.get("tipo") or "").strip(),
        str(registro.get("data_hora_texto") or "").strip(),
        str(registro.get("identificador") or "").strip(),
        str(registro.get("crc") or "").strip(),
    )
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()


def extrair_marcacoes(afd, layout):
    from services.espelho import EspelhoAFD

    processador = EspelhoAFD(layout=layout)
    linhas = afd.encode("iso-8859-1", errors="replace") if isinstance(afd, str) else afd
    registros = []
    for linha in linhas.splitlines():
        if processador._tipo_registro(linha) != "3":
            continue
        registro = processador._ler_marcacao(linha, layout)
        if registro:
            registros.append(registro)
    return registros


def importar_marcacoes(db, loja_id, afd, layout):
    inseridas = 0
    ignoradas = 0
    for registro in extrair_marcacoes(afd, layout):
        assinatura = assinatura_marcacao(loja_id, registro)
        existente = db.query(MarcacaoAFD.id).filter(
            MarcacaoAFD.loja_id == loja_id,
            MarcacaoAFD.assinatura == assinatura
        ).first()
        if existente:
            ignoradas += 1
            continue
        db.add(MarcacaoAFD(
            loja_id=loja_id,
            nsr=str(registro.get("nsr") or ""),
            tipo=registro.get("tipo"),
            layout=str(registro.get("layout") or layout),
            identificador=registro.get("identificador"),
            cpf=registro.get("cpf"),
            pis=registro.get("pis"),
            data_hora=registro["data_hora"],
            crc=registro.get("crc"),
            raw=registro.get("raw"),
            assinatura=assinatura,
            importado_em=datetime.utcnow()
        ))
        inseridas += 1
    db.commit()
    return {"inseridas": inseridas, "ignoradas": ignoradas}


def diagnosticar_marcacoes(db, loja_id=None):
    query = db.query(MarcacaoAFD)
    if loja_id is not None:
        query = query.filter(MarcacaoAFD.loja_id == loja_id)
    registros = query.order_by(MarcacaoAFD.loja_id, MarcacaoAFD.nsr, MarcacaoAFD.id).all()
    por_nsr = defaultdict(list)
    for registro in registros:
        por_nsr[(registro.loja_id, registro.nsr)].append(registro)
    conflitos = [grupo for grupo in por_nsr.values() if len({item.assinatura for item in grupo}) > 1]
    return {
        "total": len(registros),
        "possiveis_reinicios_nsr": len(conflitos),
        "grupos": [
            [{"id": item.id, "loja_id": item.loja_id, "nsr": item.nsr, "data_hora": item.data_hora.isoformat(), "assinatura": item.assinatura} for item in grupo]
            for grupo in conflitos
        ]
    }


def reparar_duplicidades(db, loja_id=None, confirmar=False):
    if not confirmar:
        raise ValueError("A reparação exige confirmação explícita.")
    query = db.query(MarcacaoAFD)
    if loja_id is not None:
        query = query.filter(MarcacaoAFD.loja_id == loja_id)
    registros = query.order_by(MarcacaoAFD.loja_id, MarcacaoAFD.data_hora, MarcacaoAFD.id).all()
    vistos = set()
    removidos = 0
    for registro in registros:
        chave = (registro.loja_id, registro.assinatura)
        if chave in vistos:
            db.delete(registro)
            removidos += 1
        else:
            vistos.add(chave)
    db.commit()
    return {"removidos": removidos}
