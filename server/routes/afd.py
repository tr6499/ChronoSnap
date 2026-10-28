from pathlib import Path
from datetime import datetime, timedelta
import asyncio
import zipfile
import tempfile
import json
import uuid

from fastapi import (
    APIRouter,
    HTTPException,
    Form,
    Request,
    UploadFile,
    File
)

from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_

from services.idclass import IDClass
from services.afd_rm import AFDRM
from services.espelho import EspelhoAFD
from services.marcacoes import extrair_marcacoes, importar_marcacoes

from database import SessionLocal
from models import (
    Funcionario,
    FuncionarioLoja,
    Loja,
    MarcacaoAFD
)


from app_paths import LOGS_DIR, DOWNLOADS_DIR

BASE_DIR = Path(
    __file__
).resolve().parent.parent


templates = Jinja2Templates(
    directory=str(
        BASE_DIR / "templates"
    )
)


router = APIRouter(
    prefix="/afd",
    tags=["AFD"]
)

AUTOMACOES_FILE = LOGS_DIR / "automacoes.json"
MAX_ARQUIVO_AFD_BYTES = 25 * 1024 * 1024


def _criar_pasta_automacoes():
    AUTOMACOES_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )


def _carregar_automacoes():
    _criar_pasta_automacoes()

    if not AUTOMACOES_FILE.exists():
        return {"automacoes": [], "ultimas_capturas": []}

    try:
        with open(AUTOMACOES_FILE, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
            if isinstance(dados, dict):
                if "automacoes" not in dados:
                    configuracao = dados.get("configuracao", {})
                    if configuracao:
                        dados["automacoes"] = [{
                            "id": "automacao-principal",
                            "nome": "Captura diária",
                            "ativo": True,
                            **configuracao
                        }]
                    else:
                        dados["automacoes"] = []
                    dados.pop("configuracao", None)
                automacoes = dados.get("automacoes", [])
                alterado = False
                for automacao in automacoes:
                    if "capturar_marcacoes" not in automacao:
                        automacao["capturar_marcacoes"] = False
                        alterado = True
                    if "intervalo_marcacoes_minutos" not in automacao:
                        automacao["intervalo_marcacoes_minutos"] = 30
                        alterado = True
                if alterado:
                    dados["automacoes"] = automacoes
                    _salvar_automacoes(dados)
                return dados
    except (json.JSONDecodeError, OSError):
        pass

    return {"automacoes": [], "ultimas_capturas": []}


def _normalizar_automacao(payload, existente=None):
    base = existente or {}
    dias_validos = {"seg", "ter", "qua", "qui", "sex", "sab", "dom"}
    dias = [dia for dia in (payload.get("dias") or base.get("dias") or []) if dia in dias_validos]
    lojas = []
    for loja in payload.get("lojas", base.get("lojas", [])):
        try:
            lojas.append(int(loja))
        except (TypeError, ValueError):
            continue

    try:
        intervalo_marcacoes = int(payload.get("intervalo_marcacoes_minutos", base.get("intervalo_marcacoes_minutos", 30)) or 30)
    except (TypeError, ValueError):
        intervalo_marcacoes = 30

    return {
        "id": base.get("id") or str(uuid.uuid4()),
        "nome": str(payload.get("nome") or base.get("nome") or "Captura diária").strip(),
        "ativo": bool(payload.get("ativo", base.get("ativo", True))),
        "hora": str(payload.get("hora") or base.get("hora") or "02:00"),
        "dias": dias or ["seg", "ter", "qua", "qui", "sex"],
        "lojas": lojas,
        "selecionar_todas": bool(payload.get("selecionar_todas", base.get("selecionar_todas", False))),
        "capturar_dia_anterior": bool(payload.get("capturar_dia_anterior", base.get("capturar_dia_anterior", True))),
        "capturar_marcacoes": bool(payload.get("capturar_marcacoes", base.get("capturar_marcacoes", False))),
        "intervalo_marcacoes_minutos": max(1, min(1440, intervalo_marcacoes)),
        "diretorio": str(payload.get("diretorio") or base.get("diretorio") or DOWNLOADS_DIR),
        "ultima_execucao": base.get("ultima_execucao"),
        "ultima_carga_marcacoes": base.get("ultima_carga_marcacoes"),
        "ultimo_status": base.get("ultimo_status")
    }


def _salvar_automacoes(dados):
    _criar_pasta_automacoes()
    with open(AUTOMACOES_FILE, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False, indent=2)


def _gerar_arquivo_rm_em_pasta(lojas, data_inicial, data_final, destino):
    afdrm = AFDRM()

    data_inicial_obj = datetime.strptime(
        data_inicial,
        "%Y-%m-%d"
    ).date()

    data_final_obj = datetime.strptime(
        data_final,
        "%Y-%m-%d"
    ).date()

    afdrm.gerar_por_lojas(
        numeros_lojas=lojas,
        data_inicial=data_inicial_obj,
        data_final=data_final_obj
    )

    caminho = Path(destino).expanduser()
    caminho.mkdir(parents=True, exist_ok=True)

    nome_arquivo = (
        f"AFD_RM_TOTVS_CONSOLIDADO_{data_inicial}_{data_final}.txt"
    )
    arquivo_rm = caminho / nome_arquivo
    afdrm.salvar(str(arquivo_rm))

    if not arquivo_rm.exists() or arquivo_rm.stat().st_size == 0:
        raise HTTPException(
            status_code=500,
            detail="O arquivo RM TOTVS não foi gerado corretamente."
        )

    return arquivo_rm


def _registrar_captura(status, lojas, diretorio, data_alvo):
    dados = _carregar_automacoes()
    registros = dados.get("ultimas_capturas", [])

    registros.insert(0, {
        "status": status,
        "lojas": lojas,
        "diretorio": diretorio,
        "data": data_alvo,
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    })

    dados["ultimas_capturas"] = registros[:5]
    _salvar_automacoes(dados)


def _executar_automacao_sync(automacao):
    lojas = automacao.get("lojas", [])
    diretorio = automacao.get("diretorio") or str(DOWNLOADS_DIR)
    data_alvo = datetime.now() - timedelta(days=1) if automacao.get("capturar_dia_anterior", True) else datetime.now()
    data_inicial = data_alvo.strftime("%Y-%m-%d")
    if automacao.get("capturar_marcacoes"):
        carregar_marcacoes_sync(lojas, data_inicial, data_inicial)
    caminho = _gerar_arquivo_rm_em_pasta(lojas, data_inicial, data_inicial, diretorio)
    return caminho, data_inicial


def _executar_carga_automatica(automacao, agora):
    lojas = automacao.get("lojas", [])
    if automacao.get("selecionar_todas"):
        db = SessionLocal()
        try:
            lojas = [numero for numero, in db.query(Loja.numero).all()]
        finally:
            db.close()
    data_alvo = agora - timedelta(days=1) if automacao.get("capturar_dia_anterior", True) else agora
    data = data_alvo.strftime("%Y-%m-%d")
    resultados = carregar_marcacoes_sync(lojas, data, data)
    return resultados


def carregar_marcacoes_sync(numeros_lojas, data_inicial, data_final):
    db = SessionLocal()
    resultados = []
    try:
        for numero in numeros_lojas:
            loja = db.query(Loja).filter(Loja.numero == int(numero)).first()
            if not loja:
                resultados.append({
                    "loja": numero,
                    "nome": f"Empresa {int(numero):02d}",
                    "erro": "Loja não encontrada."
                })
                continue
            try:
                equipamento = IDClass(
                    ip=loja.ip,
                    username=loja.usuario or "admin",
                    password=loja.senha or "7070"
                )
                equipamento.login_device()
                try:
                    mode, layout = obter_mode_layout(loja)
                    afd = equipamento.get_afd(
                        data_inicial=converter_data(data_inicial, "Data inicial"),
                        data_final=converter_data(data_final, "Data final"),
                        mode=mode
                    )
                    if not afd:
                        raise ValueError("O relógio não retornou AFD.")
                    resultado = importar_marcacoes(db, loja.id, afd, layout)
                    resultados.append({
                        "loja": numero,
                        "nome": loja.nome,
                        "success": True,
                        **resultado
                    })
                finally:
                    equipamento.logout()
            except Exception as erro:
                resultados.append({
                    "loja": numero,
                    "nome": loja.nome,
                    "success": False,
                    "erro": str(erro)
                })
        return resultados
    finally:
        db.close()


@router.post("/marcacoes/carga")
async def carga_manual_marcacoes(request: Request):
    payload = await request.json()
    lojas = payload.get("lojas") or []
    if payload.get("selecionar_todas"):
        db = SessionLocal()
        try:
            lojas = [numero for numero, in db.query(Loja.numero).all()]
        finally:
            db.close()
    if not lojas:
        raise HTTPException(status_code=400, detail="Selecione ao menos uma empresa.")
    data_inicial = payload.get("data_inicial")
    data_final = payload.get("data_final") or data_inicial
    if not data_inicial or not data_final:
        raise HTTPException(status_code=400, detail="Informe o período da carga.")
    if converter_data(data_inicial, "Data inicial") > converter_data(data_final, "Data final"):
        raise HTTPException(status_code=400, detail="A data inicial não pode ser maior que a final.")
    resultados = await asyncio.to_thread(carregar_marcacoes_sync, lojas, data_inicial, data_final)
    return {"success": True, "resultados": resultados}


@router.post("/marcacoes/arquivo")
def importar_arquivo_afd(
    loja_numero: str = Form(...),
    layout: str = Form("auto"),
    arquivo: UploadFile = File(...)
):
    if layout not in ("auto", "legado", "671"):
        raise HTTPException(
            status_code=400,
            detail="Selecione um formato AFD válido."
        )

    conteudo = arquivo.file.read(MAX_ARQUIVO_AFD_BYTES + 1)
    if not conteudo:
        raise HTTPException(
            status_code=400,
            detail="Selecione um arquivo AFD não vazio."
        )
    if len(conteudo) > MAX_ARQUIVO_AFD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="O arquivo AFD excede o limite de 25 MB."
        )
    if conteudo.startswith(b"\xef\xbb\xbf"):
        conteudo = conteudo[3:]
    if b"\x00" in conteudo:
        raise HTTPException(
            status_code=400,
            detail="O arquivo selecionado não parece ser um AFD de texto."
        )

    try:
        numero_empresa = int(loja_numero)
    except (TypeError, ValueError) as erro:
        raise HTTPException(
            status_code=400,
            detail="Selecione uma empresa válida."
        ) from erro

    db = SessionLocal()
    try:
        loja = db.query(Loja).filter(
            Loja.numero == numero_empresa
        ).first()
        if not loja:
            raise HTTPException(
                status_code=404,
                detail="Empresa não encontrada."
            )

        processador = EspelhoAFD(
            layout=None if layout == "auto" else layout
        )
        try:
            layout_detectado = processador.detectar_layout(conteudo)
            registros = extrair_marcacoes(conteudo, layout_detectado)
        except (TypeError, ValueError) as erro:
            raise HTTPException(
                status_code=400,
                detail=str(erro)
            ) from erro

        if not registros:
            raise HTTPException(
                status_code=400,
                detail="Nenhuma marcação válida foi encontrada no arquivo."
            )

        resultado = importar_marcacoes(
            db,
            loja.id,
            conteudo,
            layout_detectado,
            registros=registros
        )
        return {
            "success": True,
            "empresa": loja.nome,
            "layout": (
                "Portaria 671"
                if layout_detectado == EspelhoAFD.LAYOUT_671
                else "Legado/595"
            ),
            "total": len(registros),
            **resultado
        }
    finally:
        db.close()


async def executar_agendador_automacoes():
    dias_semana = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
    executadas_no_minuto = set()

    while True:
        agora = datetime.now()
        chave_minuto = agora.strftime("%Y-%m-%d %H:%M")
        dia_atual = dias_semana[agora.weekday()]
        dados = _carregar_automacoes()

        for automacao in dados.get("automacoes", []):
            identificador = automacao.get("id")
            chave_execucao = f"{identificador}:{chave_minuto}"
            if (
                automacao.get("ativo", True)
                and automacao.get("hora") == agora.strftime("%H:%M")
                and dia_atual in automacao.get("dias", [])
                and automacao.get("lojas")
                and chave_execucao not in executadas_no_minuto
            ):
                executadas_no_minuto.add(chave_execucao)
                try:
                    caminho, data_alvo = await asyncio.to_thread(_executar_automacao_sync, automacao)
                    _registrar_captura("ok", automacao["lojas"], automacao.get("diretorio"), data_alvo)
                except Exception:
                    _registrar_captura("erro", automacao["lojas"], automacao.get("diretorio"), agora.strftime("%Y-%m-%d"))

            if automacao.get("ativo", True) and automacao.get("capturar_marcacoes"):
                ultima = automacao.get("ultima_carga_marcacoes")
                try:
                    ultima_data = datetime.fromisoformat(ultima) if ultima else None
                except ValueError:
                    ultima_data = None
                intervalo = max(1, int(automacao.get("intervalo_marcacoes_minutos", 30)))
                if ultima_data is None or agora - ultima_data >= timedelta(minutes=intervalo):
                    try:
                        resultados = await asyncio.to_thread(_executar_carga_automatica, automacao, agora)
                        automacao["ultima_carga_marcacoes"] = agora.isoformat(timespec="seconds")
                        automacao["ultimo_status_marcacoes"] = "ok"
                        _salvar_automacoes(dados)
                        _registrar_captura("marcacoes_ok", automacao.get("lojas", []), "banco de dados", agora.strftime("%Y-%m-%d"))
                    except Exception as erro:
                        automacao["ultima_carga_marcacoes"] = agora.isoformat(timespec="seconds")
                        automacao["ultimo_status_marcacoes"] = str(erro)
                        _salvar_automacoes(dados)
                        _registrar_captura("marcacoes_erro", automacao.get("lojas", []), "banco de dados", agora.strftime("%Y-%m-%d"))

        if len(executadas_no_minuto) > 500:
            executadas_no_minuto = {item for item in executadas_no_minuto if item.endswith(agora.strftime("%Y-%m-%d %H:%M"))}

        await asyncio.sleep(20)


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def obter_mode_layout(loja):

    valor = (
        str(
            loja.afd_layout
            or "legado"
        )
        .strip()
        .lower()
    )

    if valor in (
        "671",
        "portaria671",
    ):

        return 671, 671

    return None, "legado"


def converter_data(
    valor,
    nome
):

    try:

        return datetime.strptime(
            valor,
            "%Y-%m-%d"
        )

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail=(
                f"{nome} inválida. "
                "Use o formato AAAA-MM-DD."
            )
        )


def nome_layout(layout):

    if layout == 671:

        return "Portaria 671"

    return "Legado"


def normalizar_identificador(valor):

    if valor is None:
        return ""

    return "".join(
        caractere
        for caractere in str(valor).strip()
        if caractere.isdigit()
    )


def chaves_identificador(valor):

    chave = normalizar_identificador(valor)

    if not chave:
        return []

    chave_numerica = chave.lstrip("0") or "0"

    if chave_numerica == chave:
        return [chave]

    return [chave, chave_numerica]


def buscar_por_identificador(indice, valor):

    for chave in chaves_identificador(valor):

        nome = indice.get(chave)

        if nome:
            return nome

    return ""


# ============================================================
# PÁGINA PRINCIPAL
# ============================================================

@router.get("/")
async def pagina_afd(
    request: Request
):

    db = SessionLocal()

    try:

        lojas = (
            db.query(Loja)
            .order_by(
                Loja.numero
            )
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="afd.html",
            context={
                "lojas": lojas
            }
        )

    finally:

        db.close()


@router.get("/automacoes")
async def pagina_automacoes(
    request: Request
):
    db = SessionLocal()

    try:
        lojas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="automacoes.html",
            context={
                "lojas": lojas,
                "automacoes": _carregar_automacoes().get("automacoes", []),
                "config_downloads": str(DOWNLOADS_DIR)
            }
        )
    finally:
        db.close()


@router.get("/importacao")
async def pagina_importacao_afd(request: Request):
    db = SessionLocal()
    try:
        lojas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )
        return templates.TemplateResponse(
            request=request,
            name="importacao_afd.html",
            context={"lojas": lojas}
        )
    finally:
        db.close()


@router.get("/automacoes/status")
async def automacoes_status():
    dados = _carregar_automacoes()
    return {
        "automacoes": dados.get("automacoes", []),
        "ultimas_capturas": dados.get("ultimas_capturas", [])
    }


@router.post("/automacoes")
async def criar_automacao(request: Request):
    payload = await request.json()
    dados = _carregar_automacoes()
    automacao = _normalizar_automacao(payload)
    dados.setdefault("automacoes", []).append(automacao)
    _salvar_automacoes(dados)
    return {"success": True, "automacao": automacao}


@router.post("/automacoes/configuracao")
async def salvar_automacoes(request: Request):
    payload = await request.json()

    dados = _carregar_automacoes()
    automacoes = dados.setdefault("automacoes", [])
    automacao = _normalizar_automacao(payload, automacoes[0] if automacoes else None)
    if automacoes:
        automacoes[0] = automacao
    else:
        automacoes.append(automacao)
    _salvar_automacoes(dados)
    return {"success": True, "automacao": automacao}


@router.put("/automacoes/{automacao_id}")
async def editar_automacao(automacao_id: str, request: Request):
    payload = await request.json()
    dados = _carregar_automacoes()
    automacoes = dados.setdefault("automacoes", [])
    for indice, atual in enumerate(automacoes):
        if atual.get("id") == automacao_id:
            automacao = _normalizar_automacao(payload, atual)
            automacoes[indice] = automacao
            _salvar_automacoes(dados)
            return {"success": True, "automacao": automacao}
    raise HTTPException(status_code=404, detail="Automação não encontrada.")


@router.post("/automacoes/{automacao_id}/captura")
async def alternar_captura_automacao(automacao_id: str, request: Request):
    payload = await request.json()
    dados = _carregar_automacoes()
    for indice, atual in enumerate(dados.setdefault("automacoes", [])):
        if atual.get("id") == automacao_id:
            atualizada = _normalizar_automacao({
                **atual,
                "capturar_marcacoes": payload.get("ativar", True),
                "intervalo_marcacoes_minutos": payload.get("intervalo_marcacoes_minutos", 30)
            }, atual)
            dados["automacoes"][indice] = atualizada
            _salvar_automacoes(dados)
            return {"success": True, "automacao": atualizada}
    raise HTTPException(status_code=404, detail="Automação não encontrada.")


@router.delete("/automacoes/{automacao_id}")
async def excluir_automacao(automacao_id: str):
    dados = _carregar_automacoes()
    automacoes = dados.setdefault("automacoes", [])
    restantes = [item for item in automacoes if item.get("id") != automacao_id]
    if len(restantes) == len(automacoes):
        raise HTTPException(status_code=404, detail="Automação não encontrada.")
    dados["automacoes"] = restantes
    _salvar_automacoes(dados)
    return {"success": True}


@router.post("/automacoes/executar")
async def executar_automacao(request: Request):
    payload = await request.json()

    lojas = [int(loja) for loja in (payload.get("lojas") or []) if str(loja).strip()]
    diretorio = str(payload.get("diretorio") or str(DOWNLOADS_DIR))
    data_hora = payload.get("data")

    if not lojas:
        raise HTTPException(status_code=400, detail="Selecione pelo menos uma loja.")

    try:
        data_alvo = datetime.strptime(data_hora, "%Y-%m-%d") if data_hora else datetime.now() - timedelta(days=1)
    except ValueError:
        data_alvo = datetime.now() - timedelta(days=1)

    data_inicial = data_alvo.strftime("%Y-%m-%d")
    data_final = data_alvo.strftime("%Y-%m-%d")

    try:
        caminho = _gerar_arquivo_rm_em_pasta(lojas, data_inicial, data_final, diretorio)
        _registrar_captura("ok", lojas, diretorio, data_inicial)
        return {
            "success": True,
            "arquivo": str(caminho),
            "data": data_inicial,
            "lojas": lojas
        }
    except HTTPException:
        _registrar_captura("erro", lojas, diretorio, data_inicial)
        raise
    except Exception as erro:
        _registrar_captura("erro", lojas, diretorio, data_inicial)
        raise HTTPException(status_code=500, detail=str(erro))


@router.post("/automacoes/{automacao_id}/executar")
async def executar_automacao_salva(automacao_id: str):
    dados = _carregar_automacoes()
    automacao = next((item for item in dados.get("automacoes", []) if item.get("id") == automacao_id), None)
    if not automacao:
        raise HTTPException(status_code=404, detail="Automação não encontrada.")
    lojas = automacao.get("lojas", [])
    if not lojas:
        raise HTTPException(status_code=400, detail="Selecione pelo menos uma loja.")
    try:
        caminho, data_alvo = await asyncio.to_thread(_executar_automacao_sync, automacao)
        _registrar_captura("ok", lojas, automacao.get("diretorio"), data_alvo)
        return {"success": True, "arquivo": str(caminho), "data": data_alvo, "lojas": lojas}
    except Exception as erro:
        _registrar_captura("erro", lojas, automacao.get("diretorio"), datetime.now().strftime("%Y-%m-%d"))
        raise HTTPException(status_code=500, detail=str(erro))


@router.get("/espelho")
async def pagina_espelho(
    request: Request
):

    db = SessionLocal()

    try:

        lojas = (
            db.query(Loja)
            .order_by(
                Loja.numero
            )
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="espelho.html",
            context={
                "lojas": lojas
            }
        )

    finally:

        db.close()


# ============================================================
# DOWNLOAD AFD ORIGINAL - UMA LOJA
# ============================================================

@router.get(
    "/download/{numero}"
)
def download_afd(
    numero: int
):

    db = SessionLocal()
    equipamento = None

    try:

        loja = (
            db.query(Loja)
            .filter(
                Loja.numero == numero
            )
            .first()
        )

        if not loja:

            raise HTTPException(
                status_code=404,
                detail="Loja não encontrada."
            )

        equipamento = IDClass(
            ip=loja.ip,
            username=(
                loja.usuario
                or "admin"
            ),
            password=(
                loja.senha
                or "7070"
            )
        )

        equipamento.login_device()

        mode, _ = obter_mode_layout(
            loja
        )

        resultado = (
            equipamento.save_afd(
                "./afd",
                mode=mode
            )
        )

        return FileResponse(
            resultado["path"],
            filename=resultado[
                "filename"
            ],
            media_type=(
                "application/octet-stream"
            )
        )

    finally:

        if equipamento:
            equipamento.logout()
        db.close()


# ============================================================
# PRÉ-VISUALIZAÇÃO / ESPELHO DE PONTO
# ============================================================

@router.post(
    "/preview"
)
def preview_afd(

    lojas: list[int] | None = Form(None),

    data_inicial: str = Form(...),

    data_final: str = Form(...),

    busca: str | None = Form(None),

    formato: str = Form(
        "rm_totvs"
    )

):

    busca = (busca or "").strip()

    if not lojas and not busca:

        raise HTTPException(
            status_code=400,
            detail=(
                "Selecione uma empresa ou informe um funcionário."
            )
        )

    if formato not in (
        "rm_totvs",
        "original"
    ):

        raise HTTPException(
            status_code=400,
            detail=(
                "Formato de AFD inválido."
            )
        )

    # ========================================================
    # DATAS
    # ========================================================

    data_ini = converter_data(
        data_inicial,
        "Data inicial"
    )

    data_fim = converter_data(
        data_final,
        "Data final"
    )

    if data_ini > data_fim:

        raise HTTPException(
            status_code=400,
            detail=(
                "A data inicial não pode "
                "ser maior que a data final."
            )
        )

    db = SessionLocal()

    try:

        if not lojas:
            termo = f"%{busca}%"
            documento = (
                busca.replace(".", "")
                .replace("-", "")
                .replace("/", "")
                .replace(" ", "")
            )
            documento_termo = f"%{documento}%"

            def sem_mascara(campo):
                return func.replace(
                    func.replace(
                        func.replace(
                            func.replace(campo, ".", ""),
                            "-", ""
                        ),
                        "/", ""
                    ),
                    " ", ""
                )

            lojas = [
                numero
                for numero, in (
                    db.query(Loja.numero)
                    .join(
                        FuncionarioLoja,
                        Loja.id == FuncionarioLoja.loja_id
                    )
                    .join(
                        Funcionario,
                        Funcionario.id == FuncionarioLoja.funcionario_id
                    )
                    .filter(
                        or_(
                            Funcionario.matricula.ilike(termo),
                            Funcionario.nome.ilike(termo),
                            Funcionario.cpf.ilike(termo),
                            Funcionario.pis.ilike(termo),
                            sem_mascara(Funcionario.cpf).ilike(documento_termo),
                            sem_mascara(Funcionario.pis).ilike(documento_termo)
                        )
                    )
                    .distinct()
                    .all()
                )
            ]

        resultado_lojas = []

        # ====================================================
        # PROCESSA CADA LOJA
        # ====================================================

        for numero in lojas:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.numero == numero
                )
                .first()
            )

            if not loja:

                resultado_lojas.append({

                    "loja":
                        numero,

                    "success":
                        False,

                    "erro":
                        "Loja não encontrada."

                })

                continue

            try:

                _, layout = obter_mode_layout(loja)
                marcacoes_banco = (
                    db.query(MarcacaoAFD)
                    .filter(
                        MarcacaoAFD.loja_id == loja.id,
                        MarcacaoAFD.data_hora >= datetime.combine(data_ini, datetime.min.time()),
                        MarcacaoAFD.data_hora <= datetime.combine(data_fim, datetime.max.time())
                    )
                    .order_by(MarcacaoAFD.data_hora, MarcacaoAFD.id)
                    .all()
                )

                if not marcacoes_banco:
                    raise ValueError(
                        "Não há marcações carregadas no banco para esta empresa "
                        "e período. Faça uma carga de marcações antes de consultar."
                    )

                linhas_afd = [
                    marcacao.raw
                    for marcacao in marcacoes_banco
                    if marcacao.raw
                ]
                if not linhas_afd:
                    raise ValueError(
                        "As marcações deste período não têm os registros AFD "
                        "necessários para a pré-visualização."
                    )

                funcionarios_por_documento = {}
                funcionarios_por_identificador = {}

                funcionarios_loja = (
                    db.query(Funcionario)
                    .join(
                        FuncionarioLoja,
                        Funcionario.id
                        == FuncionarioLoja.funcionario_id
                    )
                    .filter(
                        FuncionarioLoja.loja_id == loja.id
                    )
                )

                if busca:
                    termo = f"%{busca}%"
                    documento = (
                        busca.replace(".", "")
                        .replace("-", "")
                        .replace("/", "")
                        .replace(" ", "")
                    )
                    documento_termo = f"%{documento}%"

                    def sem_mascara(campo):
                        return func.replace(
                            func.replace(
                                func.replace(
                                    func.replace(campo, ".", ""),
                                    "-", ""
                                ),
                                "/", ""
                            ),
                            " ", ""
                        )

                    funcionarios_loja = funcionarios_loja.filter(
                        or_(
                            Funcionario.matricula.ilike(termo),
                            Funcionario.nome.ilike(termo),
                            Funcionario.cpf.ilike(termo),
                            Funcionario.pis.ilike(termo),
                            sem_mascara(Funcionario.cpf).ilike(documento_termo),
                            sem_mascara(Funcionario.pis).ilike(documento_termo)
                        )
                    )

                funcionarios_loja = funcionarios_loja.all()

                busca_normalizada = (
                    busca.casefold().replace(".", "")
                    .replace("-", "").replace("/", "")
                    .replace(" ", "")
                )

                for funcionario_cadastrado in funcionarios_loja:

                    for identificador in (
                        funcionario_cadastrado.pis,
                        funcionario_cadastrado.cpf,
                        funcionario_cadastrado.matricula,
                        funcionario_cadastrado.identificador_afd,
                    ):

                        for chave in chaves_identificador(
                            identificador
                        ):

                            funcionarios_por_documento[
                                chave
                            ] = funcionario_cadastrado.nome
                            funcionarios_por_identificador[
                                chave
                            ] = funcionario_cadastrado

                # =================================================
                # RECONSTRÓI O AFD A PARTIR DAS MARCAÇÕES DO BANCO
                # =================================================

                afd = "\r\n".join(linhas_afd).encode(
                    "iso-8859-1",
                    errors="replace"
                )

                # =================================================
                # PROCESSA ESPELHO
                # =================================================

                espelho = EspelhoAFD(
                    layout=layout
                )

                resultado = (
                    espelho.processar(

                        afd,

                        layout=layout,

                        data_inicial=data_ini,

                        data_final=data_fim

                    )
                )

                # =================================================
                # FUNCIONÁRIOS
                # =================================================

                funcionarios_json = []

                for funcionario in (
                    resultado.get(
                        "funcionarios",
                        []
                    )
                ):

                    # ---------------------------------------------
                    # MARCAÇÕES
                    # ---------------------------------------------

                    marcacoes = (
                        funcionario.get(
                            "marcacoes",
                            []
                        )
                    )

                    if not marcacoes:
                        continue

                    # ---------------------------------------------
                    # DOCUMENTO
                    # ---------------------------------------------

                    if layout == 671:

                        documento = (
                            funcionario.get(
                                "cpf"
                            )
                            or funcionario.get(
                                "identificador"
                            )
                            or ""
                        )

                        tipo_documento = "CPF"

                    else:

                        documento = (
                            funcionario.get(
                                "pis"
                            )
                            or funcionario.get(
                                "identificador"
                            )
                            or ""
                        )

                        tipo_documento = "PIS"

                    # ---------------------------------------------
                    # NORMALIZA DOCUMENTO
                    # ---------------------------------------------

                    chave_documento = normalizar_identificador(
                        documento
                    )

                    # ---------------------------------------------
                    # NOME VINDO DO AFD
                    # ---------------------------------------------

                    nome = (
                        funcionario.get(
                            "nome"
                        )
                        or ""
                    )

                    nome = (
                        str(
                            nome
                        )
                        .strip()
                    )

                    # ---------------------------------------------
                    # SE NÃO TEM NOME, PROCURA NO RELÓGIO
                    # ---------------------------------------------

                    nome_invalido = (
                        not nome
                        or nome.lower()
                        in (
                            "funcionário",
                            "funcionario",
                            "funcionário não cadastrado",
                            "funcionario não cadastrado",
                            "funcionário sem nome",
                            "funcionario sem nome",
                        )
                    )

                    if nome_invalido:

                        nome = buscar_por_identificador(
                            funcionarios_por_documento,
                            documento
                        )

                    if busca:
                        valores_busca = (
                            funcionario.get("matricula"),
                            funcionario.get("nome"),
                            nome,
                            funcionario.get("cpf"),
                            funcionario.get("pis"),
                            funcionario.get("identificador"),
                            documento,
                        )
                        corresponde_busca = any(
                            busca_normalizada in str(valor).casefold()
                            .replace(".", "")
                            .replace("-", "")
                            .replace("/", "")
                            .replace(" ", "")
                            for valor in valores_busca
                            if valor
                        )

                        funcionario_cadastrado = None
                        for identificador in (
                            funcionario.get("identificador"),
                            documento,
                            *(
                                marcacao.get("identificador")
                                for marcacao in marcacoes
                            )
                        ):
                            funcionario_cadastrado = next(
                                (
                                    funcionarios_por_identificador.get(chave)
                                    for chave in chaves_identificador(identificador)
                                    if funcionarios_por_identificador.get(chave)
                                ),
                                None
                            )
                            if funcionario_cadastrado:
                                break

                        if funcionario_cadastrado:
                            valores_cadastrados = (
                                funcionario_cadastrado.matricula,
                                funcionario_cadastrado.nome,
                                funcionario_cadastrado.cpf,
                                funcionario_cadastrado.pis,
                                funcionario_cadastrado.identificador_afd,
                            )
                            corresponde_busca = corresponde_busca or any(
                                busca_normalizada in str(valor).casefold()
                                .replace(".", "")
                                .replace("-", "")
                                .replace("/", "")
                                .replace(" ", "")
                                for valor in valores_cadastrados
                                if valor
                            )

                        if not corresponde_busca:
                            continue

                    # ---------------------------------------------
                    # SEGUNDA TENTATIVA:
                    #
                    # Se o funcionário não trouxe CPF/PIS,
                    # tenta usar o identificador existente
                    # nas próprias marcações.
                    # ---------------------------------------------

                    if not nome:

                        for marcacao in marcacoes:

                            identificador_marcacao = (
                                marcacao.get(
                                    "identificador"
                                )
                            )

                            if (
                                identificador_marcacao
                                is None
                            ):
                                continue

                            nome_encontrado = buscar_por_identificador(
                                funcionarios_por_documento,
                                identificador_marcacao
                            )

                            if nome_encontrado:

                                nome = (
                                    nome_encontrado
                                )

                                # Se o documento estava
                                # vazio, aproveita o
                                # identificador da marcação.
                                if not documento:

                                    documento = (
                                        str(
                                            identificador_marcacao
                                        )
                                    )

                                    chave_documento = normalizar_identificador(
                                        identificador_marcacao
                                    )

                                break

                    # ---------------------------------------------
                    # NOME FINAL
                    # ---------------------------------------------

                    if not nome:

                        nome = (
                            "Funcionário "
                            "não cadastrado"
                        )

                    # ---------------------------------------------
                    # MARCAÇÕES JSON
                    # ---------------------------------------------

                    marcacoes_json = []

                    for marcacao in marcacoes:

                        data_hora = (
                            marcacao.get(
                                "data_hora"
                            )
                        )

                        if not data_hora:
                            continue

                        marcacoes_json.append({

                            "nsr":
                                marcacao.get(
                                    "nsr"
                                ),

                            "data":
                                data_hora.strftime(
                                    "%d/%m/%Y"
                                ),

                            "hora":
                                data_hora.strftime(
                                    "%H:%M:%S"
                                ),

                            "documento":
                                documento,

                            "identificador":
                                marcacao.get(
                                    "identificador"
                                )

                        })

                    if not marcacoes_json:
                        continue

                    # ---------------------------------------------
                    # FUNCIONÁRIO FINAL
                    # ---------------------------------------------

                    funcionarios_json.append({

                        "nome":
                            nome,

                        "documento":
                            documento,

                        "tipo_documento":
                            tipo_documento,

                        "pis":
                            funcionario.get(
                                "pis"
                            ),

                        "cpf":
                            funcionario.get(
                                "cpf"
                            ),

                        "total_marcacoes":
                            len(
                                marcacoes_json
                            ),

                        "marcacoes":
                            marcacoes_json

                    })

                # =================================================
                # RESULTADO DA LOJA
                # =================================================

                resultado_lojas.append({

                    "loja":
                        numero,

                    "nome":
                        loja.nome,

                    "success":
                        True,

                    "layout":
                        nome_layout(
                            layout
                        ),

                    "total_funcionarios":
                        len(
                            funcionarios_json
                        ),

                    "total_marcacoes":
                        sum(
                            funcionario[
                                "total_marcacoes"
                            ]
                            for funcionario
                            in funcionarios_json
                        ),

                    "funcionarios":
                        funcionarios_json

                })

            except Exception as erro:

                resultado_lojas.append({

                    "loja":
                        numero,

                    "nome":
                        loja.nome,

                    "success":
                        False,

                    "erro":
                        str(erro)

                })

        # ========================================================
        # TOTAIS GERAIS
        # ========================================================

        total_funcionarios = sum(

            loja_resultado.get(
                "total_funcionarios",
                0
            )

            for loja_resultado
            in resultado_lojas

            if loja_resultado.get(
                "success"
            )

        )

        total_marcacoes = sum(

            loja_resultado.get(
                "total_marcacoes",
                0
            )

            for loja_resultado
            in resultado_lojas

            if loja_resultado.get(
                "success"
            )

        )

        # ========================================================
        # RESPOSTA
        # ========================================================

        return {

            "success":
                True,

            "formato":
                formato,

            "data_inicial":
                data_inicial,

            "data_final":
                data_final,

            "lojas":
                resultado_lojas,

            "total_funcionarios":
                total_funcionarios,

            "total_marcacoes":
                total_marcacoes

        }

    finally:

        db.close()
        

# ============================================================
# GERAR / BAIXAR AFD
# ============================================================

@router.post(
    "/download"
)
def gerar_download_afd(

    lojas: list[int] = Form(...),

    data_inicial: str = Form(...),

    data_final: str = Form(...),

    formato: str = Form(
        "rm_totvs"
    )

):

    # ========================================================
    # VALIDAÇÕES
    # ========================================================

    if not lojas:

        raise HTTPException(
            status_code=400,
            detail=(
                "Nenhuma loja selecionada."
            )
        )

    if formato not in (
        "rm_totvs",
        "original"
    ):

        raise HTTPException(
            status_code=400,
            detail="Formato inválido."
        )

    data_ini = converter_data(
        data_inicial,
        "Data inicial"
    )

    data_fim = converter_data(
        data_final,
        "Data final"
    )

    if data_ini > data_fim:

        raise HTTPException(
            status_code=400,
            detail=(
                "A data inicial não pode "
                "ser maior que a data final."
            )
        )

    # ========================================================
    # PASTA TEMPORÁRIA
    # ========================================================

    pasta = Path(
        tempfile.mkdtemp(
            prefix="afd_"
        )
    )

    db = SessionLocal()

    try:

        # ====================================================
        # AFD ORIGINAL
        # ====================================================

        if formato == "original":

            arquivos = []

            for numero in lojas:

                loja = (
                    db.query(Loja)
                    .filter(
                        Loja.numero == numero
                    )
                    .first()
                )

                if not loja:
                    continue

                equipamento = IDClass(

                    ip=loja.ip,

                    username=(
                        loja.usuario
                        or "admin"
                    ),

                    password=(
                        loja.senha
                        or "7070"
                    )

                )

                equipamento.login_device()

                try:
                    mode, _ = (
                        obter_mode_layout(
                            loja
                        )
                    )

                    resultado = (
                        equipamento.download_afd(

                            output_dir=str(
                                pasta
                            ),

                            data_inicial=data_ini,

                            data_final=data_fim,

                            mode=mode

                        )
                    )

                    caminho = Path(
                        resultado["path"]
                    )

                    if caminho.exists():

                        arquivos.append(
                            caminho
                        )
                finally:
                    equipamento.logout()

            if not arquivos:

                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Nenhum AFD foi gerado."
                    )
                )

            # ------------------------------------------------
            # Uma loja
            # ------------------------------------------------

            if len(arquivos) == 1:

                arquivo = arquivos[0]

                return FileResponse(

                    arquivo,

                    filename=arquivo.name,

                    media_type=(
                        "application/octet-stream"
                    )

                )

            # ------------------------------------------------
            # Várias lojas
            # ------------------------------------------------

            zip_path = (
                pasta /
                (
                    "AFD_ORIGINAL_"
                    f"{data_inicial}_"
                    f"{data_final}.zip"
                )
            )

            with zipfile.ZipFile(

                zip_path,

                "w",

                zipfile.ZIP_DEFLATED

            ) as zip_file:

                for arquivo in arquivos:

                    zip_file.write(

                        arquivo,

                        arcname=arquivo.name

                    )

            return FileResponse(

                zip_path,

                filename=zip_path.name,

                media_type=(
                    "application/zip"
                )

            )

        # ====================================================
        # RM TOTVS CONSOLIDADO
        # ====================================================

        afdrm = AFDRM()

        afdrm.gerar_por_lojas(

            numeros_lojas=lojas,

            data_inicial=data_ini,

            data_final=data_fim

        )

        arquivo_rm = (
            pasta /
            (
                "AFD_RM_TOTVS_"
                f"{data_inicial}_"
                f"{data_final}.txt"
            )
        )

        afdrm.salvar(
            str(arquivo_rm)
        )

        if not arquivo_rm.exists():

            raise HTTPException(
                status_code=500,
                detail=(
                    "O arquivo RM TOTVS "
                    "não foi gerado."
                )
            )

        if arquivo_rm.stat().st_size == 0:

            raise HTTPException(
                status_code=500,
                detail=(
                    "O arquivo RM TOTVS "
                    "está vazio."
                )
            )

        return FileResponse(

            arquivo_rm,

            filename=arquivo_rm.name,

            media_type=(
                "application/octet-stream"
            )

        )

    finally:

        db.close()