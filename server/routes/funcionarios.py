import json
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import SessionLocal

from models import (
    Funcionario,
    FuncionarioLoja,
    Loja,
    UsuarioRelogio
)

from services.idclass import IDClass


BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

router = APIRouter()


def _proximo_identificador(campo):
    db = SessionLocal()

    try:
        valores = []
        for modelo in (Funcionario, UsuarioRelogio):
            coluna = getattr(modelo, campo)
            valores.extend(
                valor
                for (valor,) in db.query(coluna).all()
                if valor is not None
            )

        numeros = []
        for valor in valores:
            try:
                numeros.append(int(str(valor)))
            except (TypeError, ValueError):
                continue

        candidato = max(numeros, default=0) + 1
        usados = {str(valor) for valor in valores}
        while str(candidato) in usados:
            candidato += 1

        return candidato
    finally:
        db.close()


def _garantir_identificadores(funcionario):
    if (
        funcionario.codigo is None
        or not _identificador_disponivel(
            funcionario,
            "codigo",
            funcionario.codigo
        )
    ):
        funcionario.codigo = None
        funcionario.codigo = _proximo_identificador("codigo")

    if (
        funcionario.rfid is None
        or not _identificador_disponivel(
            funcionario,
            "rfid",
            funcionario.rfid
        )
    ):
        funcionario.rfid = None
        funcionario.rfid = _proximo_identificador("rfid")

    if (
        not funcionario.bars
        or not _identificador_disponivel(
            funcionario,
            "bars",
            funcionario.bars
        )
    ):
        funcionario.bars = None
        funcionario.bars = str(
            _proximo_identificador("bars")
        )


def _identificador_disponivel(funcionario, campo, valor):
    db = SessionLocal()

    try:
        funcionario_existente = db.query(Funcionario).filter(
            getattr(Funcionario, campo) == valor,
            Funcionario.id != funcionario.id
        ).first()

        if funcionario_existente:
            return False

        usuario_existente = db.query(UsuarioRelogio).filter(
            getattr(UsuarioRelogio, campo) == valor,
            UsuarioRelogio.numero_cracha != str(funcionario.matricula)
        ).first()

        return usuario_existente is None
    finally:
        db.close()


def _inteiro_opcional(valor, nome):
    valor = str(valor or "").strip()
    if not valor:
        return None

    try:
        return int(valor)
    except ValueError as erro:
        raise HTTPException(
            status_code=400,
            detail=f"{nome} deve conter apenas números."
        ) from erro

# ============================================================
# SINCRONIZA FUNCIONÁRIO COM UM RELÓGIO
# ============================================================

def sincronizar_funcionario_relogio(
    funcionario,
    loja,
    operacao,
    enviar_biometrias=True
):

    equipamento = None

    biometrias = []
    if enviar_biometrias and funcionario.biometrias:
        try:
            biometrias = json.loads(funcionario.biometrias)
        except (TypeError, ValueError):
            biometrias = []

    try:

        layout = (
            loja.afd_layout or "legado"
        ).lower().strip()

        # ----------------------------------------------------
        # DEFINIR MODO
        # ----------------------------------------------------

        if layout in ("671", "portaria671"):
            mode = 671
            identificador_chave = "cpf"
            identificador = funcionario.cpf
        else:
            mode = 0
            identificador_chave = "pis"
            identificador = funcionario.pis

        if operacao != "excluir" and not identificador:
            descricao = "CPF" if mode == 671 else "PIS"
            raise Exception(
                f"Funcionário não possui {descricao} "
                f"para o modo {'Portaria 671' if mode == 671 else 'Legado'}."
            )

        # ----------------------------------------------------
        # CONECTAR
        # ----------------------------------------------------

        equipamento = IDClass(
            loja.ip,
            username=loja.usuario or "admin",
            password=loja.senha or "7070",
            timeout=30
        )

        equipamento.login_device()

        usuario_existente = equipamento.get_user_by_registration(
            funcionario.matricula,
            mode=mode
        )

        if usuario_existente:
            identificador_relogio = usuario_existente.get(
                identificador_chave
            )
            if identificador_relogio is not None:
                if identificador_chave == "cpf":
                    funcionario.cpf = str(identificador_relogio)
                else:
                    funcionario.pis = str(identificador_relogio)

            for atributo, chave in (
                ("codigo", "code"),
                ("rfid", "rfid"),
                ("bars", "bars"),
            ):
                valor = usuario_existente.get(chave)
                if (
                    valor is not None
                    and str(valor).strip()
                    and _identificador_disponivel(
                        funcionario,
                        atributo,
                        valor
                    )
                ):
                    setattr(funcionario, atributo, valor)

        if operacao != "excluir":
            _garantir_identificadores(funcionario)

        # ----------------------------------------------------
        # OPERAÇÃO
        # ----------------------------------------------------

        if operacao in ("adicionar", "atualizar"):
            if usuario_existente:
                resposta = equipamento.atualizar_usuario(
                    nome=funcionario.nome,
                    matricula=funcionario.matricula,
                    cpf=funcionario.cpf,
                    pis=funcionario.pis,
                    codigo=funcionario.codigo,
                    rfid=funcionario.rfid,
                    bars=funcionario.bars,
                    admin=funcionario.administrador,
                    templates=biometrias,
                    mode=mode
                )
                mensagem = (
                    "Funcionário já existia e foi atualizado no relógio."
                    if operacao == "adicionar"
                    else "Funcionário atualizado no relógio."
                )
            else:
                resposta = equipamento.cadastrar_usuario(
                    nome=funcionario.nome,
                    matricula=funcionario.matricula,
                    cpf=funcionario.cpf,
                    pis=funcionario.pis,
                    codigo=funcionario.codigo,
                    rfid=funcionario.rfid,
                    bars=funcionario.bars,
                    admin=funcionario.administrador,
                    templates=biometrias,
                    mode=mode
                )
                mensagem = "Funcionário cadastrado no relógio."

        elif operacao == "excluir":

            if not usuario_existente:
                return {
                    "success": True,
                    "loja_id": loja.id,
                    "loja": loja.numero,
                    "nome": loja.nome,
                    "layout": layout,
                    "mode": mode,
                    "operacao": operacao,
                    "mensagem": "Funcionário já não estava cadastrado no relógio."
                }

            resposta = equipamento.excluir_usuario(
                matricula=funcionario.matricula,
                cpf=funcionario.cpf,
                pis=funcionario.pis,
                mode=mode
            )

            if not resposta.get("success"):

                raise Exception(
                    resposta.get(
                        "mensagem",
                        "Funcionário não encontrado no relógio."
                    )
                )

            mensagem = "Funcionário removido do relógio."

        else:

            raise Exception(
                f"Operação inválida: {operacao}"
            )

        return {
            "success": True,
            "loja_id": loja.id,
            "loja": loja.numero,
            "nome": loja.nome,
            "layout": layout,
            "mode": mode,
            "operacao": operacao,
            "mensagem": mensagem,
            "resposta": resposta
        }

    except Exception as e:

        return {
            "success": False,
            "loja_id": loja.id,
            "loja": loja.numero,
            "nome": loja.nome,
            "layout":
                loja.afd_layout or "legado",
            "operacao": operacao,
            "mensagem": str(e)
        }

    finally:

        if equipamento:

            try:
                equipamento.logout()
            except Exception:
                pass


# ============================================================
# LISTAGEM
# ============================================================

@router.get("/funcionarios")
async def funcionarios_page(
    request: Request,
    loja_id: str | None = None,
    busca: str | None = None
):

    db: Session = SessionLocal()

    try:

        todas_empresas = loja_id == "todas"
        loja_id = int(loja_id) if loja_id and loja_id.isdigit() else None

        lojas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        funcionarios = []
        busca = (busca or "").strip()

        if busca:
            loja_id = None

        if loja_id is not None or busca or todas_empresas:

            query = db.query(Funcionario)

            query = (
                query
                .join(
                    FuncionarioLoja,
                    Funcionario.id ==
                    FuncionarioLoja.funcionario_id
                )
            )

            if loja_id is not None:
                query = query.filter(
                    FuncionarioLoja.loja_id == loja_id
                )

            if busca:
                termo = f"%{busca}%"
                documento = busca.replace(".", "").replace("-", "").replace("/", "").replace(" ", "")
                documento_termo = f"%{documento}%"
                cpf_sem_mascara = func.replace(
                    func.replace(
                        func.replace(
                            func.replace(Funcionario.cpf, ".", ""),
                            "-", ""
                        ),
                        "/", ""
                    ),
                    " ", ""
                )
                pis_sem_mascara = func.replace(
                    func.replace(
                        func.replace(
                            func.replace(Funcionario.pis, ".", ""),
                            "-", ""
                        ),
                        "/", ""
                    ),
                    " ", ""
                )
                query = query.filter(
                    or_(
                        Funcionario.matricula.ilike(termo),
                        Funcionario.nome.ilike(termo),
                        Funcionario.cpf.ilike(termo),
                        Funcionario.pis.ilike(termo),
                        cpf_sem_mascara.ilike(documento_termo),
                        pis_sem_mascara.ilike(documento_termo)
                    )
                )

            if todas_empresas:
                query = query.distinct()

            funcionarios = (
                query
                .order_by(Funcionario.nome)
                .all()
            )

        funcionarios_lojas = {}

        for funcionario in funcionarios:

            relacionamentos = (
                db.query(FuncionarioLoja)
                .filter(
                    FuncionarioLoja.funcionario_id
                    == funcionario.id
                )
                .all()
            )

            loja_ids = [
                relacionamento.loja_id
                for relacionamento in relacionamentos
            ]

            lojas_funcionario = (
                db.query(Loja)
                .filter(
                    Loja.id.in_(loja_ids)
                )
                .order_by(Loja.numero)
                .all()
                if loja_ids
                else []
            )

            funcionarios_lojas[
                funcionario.id
            ] = lojas_funcionario

        return templates.TemplateResponse(
            request=request,
            name="funcionarios.html",
            context={
                "funcionarios": funcionarios,
                "lojas": lojas,
                "loja_id": loja_id,
                "todas_empresas": todas_empresas,
                "busca": busca or "",
                "funcionarios_lojas": funcionarios_lojas,
                "total_funcionarios": len(funcionarios),
                "total_funcionarios_ativos": sum(
                    1 for funcionario in funcionarios
                    if funcionario.ativo
                ),
                "total_funcionarios_inativos": sum(
                    1 for funcionario in funcionarios
                    if not funcionario.ativo
                )
            }
        )

    finally:

        db.close()


# ============================================================
# PÁGINA DE CADASTRO
# ============================================================

@router.get("/funcionarios/novo")
async def novo_funcionario_page(
    request: Request
):

    db: Session = SessionLocal()

    try:

        lojas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        return templates.TemplateResponse(
            request=request,
            name="funcionario_novo.html",
            context={
                "lojas": lojas
            }
        )

    finally:

        db.close()


# ============================================================
# ADICIONAR FUNCIONÁRIO
# ============================================================

@router.post("/funcionarios")
async def adicionar_funcionario(

    matricula: str = Form(...),
    nome: str = Form(...),
    pis: str = Form(""),
    cpf: str = Form(""),
    codigo: str = Form(""),
    rfid: str = Form(""),
    bars: str = Form(""),
    ativo: str = Form("true"),
    administrador: str = Form("false"),
    enviar_biometrias: str = Form("true"),
    lojas: list[int] = Form([])

):

    db: Session = SessionLocal()

    try:

        matricula = matricula.strip()
        nome = nome.strip()
        pis = pis.strip() or None
        cpf = cpf.strip() or None
        codigo = _inteiro_opcional(codigo, "Code")
        rfid = _inteiro_opcional(rfid, "RFID")
        bars = bars.strip() or None

        existente = (
            db.query(Funcionario)
            .filter(
                Funcionario.matricula == matricula
            )
            .first()
        )

        if existente:

            raise HTTPException(
                status_code=400,
                detail="Já existe funcionário com essa matrícula."
            )

        funcionario = Funcionario(
            matricula=matricula,
            nome=nome,
            pis=pis,
            cpf=cpf,
            ativo=(ativo == "true"),
            administrador=(administrador == "true")
            ,
            biometrias=None,
            codigo=codigo,
            rfid=rfid,
            bars=bars
        )

        db.add(funcionario)

        db.flush()

        _garantir_identificadores(funcionario)

        for loja_id in lojas:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if loja:

                db.add(
                    FuncionarioLoja(
                        funcionario_id=funcionario.id,
                        loja_id=loja.id
                    )
                )

        resultados = []

        for loja_id in lojas:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if not loja:
                continue

            resultados.append(
                sincronizar_funcionario_relogio(
                    funcionario,
                    loja,
                    "adicionar",
                    enviar_biometrias=(enviar_biometrias == "true")
                )
            )

        falhas = [
            resultado
            for resultado in resultados
            if not resultado["success"]
        ]

        if falhas:

            detalhes = " | ".join(
                f"Loja {resultado['loja']:02d}: "
                f"{resultado['mensagem']}"
                for resultado in falhas
            )

            db.rollback()

            return RedirectResponse(
                url=(
                    "/funcionarios"
                    "?erro=Funcionário não foi cadastrado. "
                    "Falha na sincronização. "
                    f"{detalhes}"
                ),
                status_code=303
            )

        db.commit()

        return RedirectResponse(
            url=(
                "/funcionarios"
                "?sucesso=Funcionário cadastrado "
                "e sincronizado com os relógios."
            ),
            status_code=303
        )

    except:

        db.rollback()

        raise

    finally:

        db.close()


# ============================================================
# EDITAR
# ============================================================

@router.get(
    "/funcionarios/{funcionario_id}/editar"
)
async def editar_funcionario(
    request: Request,
    funcionario_id: int
):

    db: Session = SessionLocal()

    try:

        funcionario = (
            db.query(Funcionario)
            .filter(
                Funcionario.id == funcionario_id
            )
            .first()
        )

        if not funcionario:

            raise HTTPException(
                status_code=404,
                detail="Funcionário não encontrado."
            )

        lojas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

        relacionamentos = (
            db.query(FuncionarioLoja)
            .filter(
                FuncionarioLoja.funcionario_id
                == funcionario.id
            )
            .all()
        )

        lojas_selecionadas = {
            relacionamento.loja_id
            for relacionamento in relacionamentos
        }

        return templates.TemplateResponse(
            request=request,
            name="funcionario_editar.html",
            context={
                "funcionario": funcionario,
                "lojas": lojas,
                "lojas_selecionadas":
                    lojas_selecionadas
            }
        )

    finally:

        db.close()


# ============================================================
# SALVAR EDIÇÃO
# ============================================================

# ============================================================
# SALVAR EDIÇÃO E SINCRONIZAR RELÓGIOS
# ============================================================

# ============================================================
# SALVAR EDIÇÃO E SINCRONIZAR RELÓGIOS
# ============================================================

@router.post(
    "/funcionarios/{funcionario_id}/editar"
)
async def salvar_funcionario(

    funcionario_id: int,

    matricula: str = Form(...),
    nome: str = Form(...),
    pis: str = Form(""),
    cpf: str = Form(""),
    codigo: str = Form(""),
    rfid: str = Form(""),
    bars: str = Form(""),
    ativo: str = Form("true"),
    administrador: str = Form("false"),
    enviar_biometrias: str = Form("true"),
    lojas: list[int] = Form([])

):

    db: Session = SessionLocal()

    resultados = []

    try:

        # ====================================================
        # BUSCAR FUNCIONÁRIO
        # ====================================================

        funcionario = (
            db.query(Funcionario)
            .filter(
                Funcionario.id == funcionario_id
            )
            .first()
        )

        if not funcionario:

            raise HTTPException(
                status_code=404,
                detail="Funcionário não encontrado."
            )

        # ====================================================
        # GUARDAR ESTADO ATUAL
        # ====================================================

        matricula_antiga = funcionario.matricula
        nome_antigo = funcionario.nome
        pis_antigo = funcionario.pis
        cpf_antigo = funcionario.cpf
        ativo_antigo = funcionario.ativo

        relacionamentos_antigos = (
            db.query(FuncionarioLoja)
            .filter(
                FuncionarioLoja.funcionario_id
                == funcionario.id
            )
            .all()
        )

        lojas_antigas = {
            relacionamento.loja_id
            for relacionamento in relacionamentos_antigos
        }

        lojas_novas = set(lojas)

        # ====================================================
        # IDENTIFICAR OPERAÇÕES
        # ====================================================

        lojas_para_atualizar = (
            lojas_antigas & lojas_novas
        )

        lojas_para_adicionar = (
            lojas_novas - lojas_antigas
        )

        lojas_para_excluir = (
            lojas_antigas - lojas_novas
        )

        # ====================================================
        # OBJETO COM DADOS NOVOS
        # ====================================================

        funcionario_novo = Funcionario(
            id=funcionario.id,
            matricula=matricula.strip(),
            nome=nome.strip(),
            pis=pis.strip() or None,
            cpf=cpf.strip() or None,
            codigo=_inteiro_opcional(codigo, "Code"),
            rfid=_inteiro_opcional(rfid, "RFID"),
            bars=bars.strip() or None,
            ativo=(ativo == "true"),
            administrador=(administrador == "true")
            ,
            biometrias=funcionario.biometrias
        )

        _garantir_identificadores(funcionario_novo)

        # ====================================================
        # OBJETO COM DADOS ANTIGOS
        # ====================================================

        funcionario_antigo = Funcionario(
            id=funcionario.id,
            matricula=matricula_antiga,
            nome=nome_antigo,
            pis=pis_antigo,
            cpf=cpf_antigo,
            ativo=ativo_antigo,
            administrador=funcionario.administrador
        )

        # ====================================================
        # 1. ATUALIZAR RELÓGIOS EXISTENTES
        # ====================================================

        for loja_id in lojas_para_atualizar:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if not loja:
                continue

            resultado = sincronizar_funcionario_relogio(
                funcionario_novo,
                loja,
                "atualizar",
                enviar_biometrias=(enviar_biometrias == "true")
            )

            resultados.append(resultado)

        # ====================================================
        # 2. CADASTRAR NOS NOVOS RELÓGIOS
        # ====================================================

        for loja_id in lojas_para_adicionar:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if not loja:
                continue

            resultado = sincronizar_funcionario_relogio(
                funcionario_novo,
                loja,
                "adicionar",
                enviar_biometrias=(enviar_biometrias == "true")
            )

            resultados.append(resultado)

        # ====================================================
        # 3. REMOVER DOS RELÓGIOS DESMARCADOS
        # ====================================================

        for loja_id in lojas_para_excluir:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if not loja:
                continue

            resultado = sincronizar_funcionario_relogio(
                funcionario_antigo,
                loja,
                "excluir"
            )

            resultados.append(resultado)

        falhas = [
            resultado
            for resultado in resultados
            if not resultado["success"]
        ]

        funcionario.matricula = matricula.strip()
        funcionario.nome = nome.strip()
        funcionario.pis = pis.strip() or None
        funcionario.cpf = cpf.strip() or None
        funcionario.codigo = funcionario_novo.codigo
        funcionario.rfid = funcionario_novo.rfid
        funcionario.bars = funcionario_novo.bars
        funcionario.ativo = ativo == "true"
        funcionario.administrador = administrador == "true"

        # ====================================================
        # ATUALIZAR ASSOCIAÇÕES
        # ====================================================

        db.query(
            FuncionarioLoja
        ).filter(
            FuncionarioLoja.funcionario_id
            == funcionario.id
        ).delete()

        for loja_id in lojas_novas:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if loja:

                db.add(
                    FuncionarioLoja(
                        funcionario_id=funcionario.id,
                        loja_id=loja.id
                    )
                )

        # ====================================================
        # COMMIT FINAL
        # ====================================================

        db.commit()

        if falhas:
            detalhes = " | ".join(
                f"Empresa {resultado['loja']:02d} ({resultado['nome']}): "
                f"{resultado['mensagem']}"
                for resultado in falhas
            )
            mensagem = (
                "Alterações salvas; falha ao sincronizar alguns relógios. "
                "Confira a conexão e tente atualizar esses relógios novamente. "
                + detalhes
            )
            return RedirectResponse(
                url=f"/funcionarios?erro={quote_plus(mensagem)}",
                status_code=303
            )

        return RedirectResponse(
            url=(
                "/funcionarios"
                "?sucesso=Funcionário+sincronizado+com+sucesso."
            ),
            status_code=303
        )

    except HTTPException:

        db.rollback()
        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        db.close()
        
async def salvar_funcionario(

    funcionario_id: int,

    matricula: str = Form(...),
    nome: str = Form(...),
    pis: str = Form(""),
    cpf: str = Form(""),
    ativo: str = Form("true"),
    administrador: str = Form("false"),
    lojas: list[int] = Form([])

):

    db: Session = SessionLocal()

    resultados = []

    try:

        # ====================================================
        # BUSCAR FUNCIONÁRIO
        # ====================================================

        funcionario = (
            db.query(Funcionario)
            .filter(
                Funcionario.id == funcionario_id
            )
            .first()
        )

        if not funcionario:

            raise HTTPException(
                status_code=404,
                detail="Funcionário não encontrado."
            )

        # ====================================================
        # GUARDAR LOJAS ANTIGAS
        # ====================================================

        relacionamentos_antigos = (
            db.query(FuncionarioLoja)
            .filter(
                FuncionarioLoja.funcionario_id
                == funcionario.id
            )
            .all()
        )

        lojas_antigas = {
            relacionamento.loja_id
            for relacionamento in relacionamentos_antigos
        }

        lojas_novas = set(lojas)

        # ====================================================
        # IDENTIFICAR ALTERAÇÕES
        # ====================================================

        lojas_para_atualizar = (
            lojas_antigas & lojas_novas
        )

        lojas_para_adicionar = (
            lojas_novas - lojas_antigas
        )

        lojas_para_excluir = (
            lojas_antigas - lojas_novas
        )

        # ====================================================
        # GUARDAR DADOS ANTIGOS
        # ====================================================

        matricula_antiga = funcionario.matricula
        pis_antigo = funcionario.pis
        cpf_antigo = funcionario.cpf
        nome_antigo = funcionario.nome

        # ====================================================
        # ATUALIZAR BANCO
        # ====================================================

        funcionario.matricula = matricula.strip()
        funcionario.nome = nome.strip()
        funcionario.pis = pis.strip() or None
        funcionario.cpf = cpf.strip() or None
        funcionario.ativo = ativo == "true"
        funcionario.administrador = administrador == "true"

        db.commit()

        # ====================================================
        # ATUALIZAR RELÓGIOS EXISTENTES
        # ====================================================

        for loja_id in lojas_para_atualizar:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if not loja:
                continue

            resultado = sincronizar_funcionario_relogio(
                funcionario,
                loja,
                "atualizar"
            )

            resultados.append(resultado)

        # ====================================================
        # CADASTRAR NOS NOVOS RELÓGIOS
        # ====================================================

        for loja_id in lojas_para_adicionar:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if not loja:
                continue

            resultado = sincronizar_funcionario_relogio(
                funcionario,
                loja,
                "adicionar"
            )

            resultados.append(resultado)

        # ====================================================
        # REMOVER DOS RELÓGIOS DESMARCADORES
        # ====================================================

        # IMPORTANTE:
        # Para remover, precisamos usar os dados antigos
        # porque a matrícula/CPF/PIS podem ter sido alterados.

        funcionario_para_exclusao = Funcionario(
            id=funcionario.id,
            matricula=matricula_antiga,
            nome=nome_antigo,
            pis=pis_antigo,
            cpf=cpf_antigo,
            ativo=funcionario.ativo,
            administrador=funcionario.administrador
        )

        for loja_id in lojas_para_excluir:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if not loja:
                continue

            resultado = sincronizar_funcionario_relogio(
                funcionario_para_exclusao,
                loja,
                "excluir"
            )

            resultados.append(resultado)

        # ====================================================
        # ATUALIZAR ASSOCIAÇÕES NO BANCO
        # ====================================================

        db.query(
            FuncionarioLoja
        ).filter(
            FuncionarioLoja.funcionario_id
            == funcionario.id
        ).delete()

        for loja_id in lojas_novas:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if loja:

                db.add(
                    FuncionarioLoja(
                        funcionario_id=funcionario.id,
                        loja_id=loja.id
                    )
                )

        db.commit()

        # ====================================================
        # VERIFICAR RESULTADOS
        # ====================================================

        falhas = [
            resultado
            for resultado in resultados
            if not resultado["success"]
        ]

        if falhas:

            detalhes = " | ".join(
                f"Loja {resultado['loja']:02d}: "
                f"{resultado['mensagem']}"
                for resultado in falhas
            )

            return RedirectResponse(
                url=(
                    "/funcionarios"
                    "?erro=Funcionário+salvo+no+sistema,+"
                    "mas+houve+falha+na+sincronização."
                    f"+{detalhes}"
                ),
                status_code=303
            )

        # ====================================================
        # SUCESSO
        # ====================================================

        return RedirectResponse(
            url=(
                "/funcionarios"
                "?sucesso=Funcionário+atualizado+com+sucesso+"
                "nos+relógios+e+no+sistema."
            ),
            status_code=303
        )

    except HTTPException:

        db.rollback()
        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        db.close()
async def salvar_funcionario(

    funcionario_id: int,

    matricula: str = Form(...),
    nome: str = Form(...),
    pis: str = Form(""),
    cpf: str = Form(""),
    ativo: str = Form("true"),
    lojas: list[int] = Form([])

):

    db: Session = SessionLocal()

    try:

        funcionario = (
            db.query(Funcionario)
            .filter(
                Funcionario.id == funcionario_id
            )
            .first()
        )

        if not funcionario:

            raise HTTPException(
                status_code=404,
                detail="Funcionário não encontrado."
            )

        funcionario.matricula = matricula.strip()
        funcionario.nome = nome.strip()
        funcionario.pis = pis.strip() or None
        funcionario.cpf = cpf.strip() or None
        funcionario.ativo = ativo == "true"

        db.query(
            FuncionarioLoja
        ).filter(
            FuncionarioLoja.funcionario_id
            == funcionario.id
        ).delete()

        for loja_id in lojas:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == loja_id
                )
                .first()
            )

            if loja:

                db.add(
                    FuncionarioLoja(
                        funcionario_id=funcionario.id,
                        loja_id=loja.id
                    )
                )

        db.commit()

        return RedirectResponse(
            url="/funcionarios",
            status_code=303
        )

    except:

        db.rollback()

        raise

    finally:

        db.close()

# ============================================================
# EXCLUIR FUNCIONÁRIO
# ============================================================

@router.post(
    "/funcionarios/{funcionario_id}/excluir"
)
async def excluir_funcionario(
    funcionario_id: int
):

    db: Session = SessionLocal()

    resultados = []

    try:

        funcionario = (
            db.query(Funcionario)
            .filter(
                Funcionario.id == funcionario_id
            )
            .first()
        )

        if not funcionario:

            raise HTTPException(
                status_code=404,
                detail="Funcionário não encontrado."
            )

        relacionamentos = (
            db.query(FuncionarioLoja)
            .filter(
                FuncionarioLoja.funcionario_id
                == funcionario.id
            )
            .all()
        )

        if not relacionamentos:

            nome = funcionario.nome

            db.delete(funcionario)
            db.commit()

            return RedirectResponse(
                url=f"/funcionarios?sucesso=Funcionário+{nome}+excluído+com+sucesso.",
                status_code=303
            )

        for relacionamento in relacionamentos:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == relacionamento.loja_id
                )
                .first()
            )

            if not loja:
                continue

            equipamento = None

            try:

                layout = (
                    loja.afd_layout or "legado"
                ).lower().strip()

                if layout in ("671", "portaria671"):

                    mode = 671

                    if not funcionario.cpf:

                        raise Exception(
                            "Funcionário não possui CPF "
                            "para o modo Portaria 671."
                        )

                else:

                    mode = 0

                    if not funcionario.pis:

                        raise Exception(
                            "Funcionário não possui PIS "
                            "para o modo Legado."
                        )

                equipamento = IDClass(
                    loja.ip,
                    username=loja.usuario or "admin",
                    password=loja.senha or "7070",
                    timeout=30
                )

                equipamento.login_device()

                resposta = equipamento.excluir_usuario(
                    matricula=funcionario.matricula,
                    cpf=funcionario.cpf,
                    pis=funcionario.pis,
                    mode=mode
                )

                if not resposta.get("success"):

                    raise Exception(
                        resposta.get(
                            "mensagem",
                            "Falha ao excluir funcionário."
                        )
                    )

                resultados.append({
                    "loja_id": loja.id,
                    "loja": loja.numero,
                    "nome": loja.nome,
                    "layout": layout,
                    "mode": mode,
                    "success": True,
                    "mensagem":
                        "Funcionário excluído do relógio."
                })

            except Exception as e:

                resultados.append({
                    "loja_id": loja.id,
                    "loja": loja.numero,
                    "nome": loja.nome,
                    "layout":
                        loja.afd_layout or "legado",
                    "success": False,
                    "mensagem": str(e)
                })

            finally:

                if equipamento:

                    try:
                        equipamento.logout()
                    except Exception:
                        pass

        # ========================================================
        # VERIFICAR RESULTADOS
        # ========================================================

        falhas = [
            resultado
            for resultado in resultados
            if not resultado["success"]
        ]

        # --------------------------------------------------------
        # SE HOUVE FALHA
        # --------------------------------------------------------

        if falhas:

            detalhes = " | ".join(
                f"Loja {resultado['loja']:02d}: "
                f"{resultado['mensagem']}"
                for resultado in falhas
            )

            return RedirectResponse(
                url=(
                    "/funcionarios"
                    "?erro=Funcionário+não+foi+excluído+do+sistema."
                    f"+{detalhes}"
                ),
                status_code=303
            )

        # ========================================================
        # TODOS OS RELÓGIOS FORAM EXCLUÍDOS
        # ========================================================

        nome = funcionario.nome

        db.query(
            FuncionarioLoja
        ).filter(
            FuncionarioLoja.funcionario_id
            == funcionario.id
        ).delete()

        db.delete(funcionario)

        db.commit()

        return RedirectResponse(
            url=(
                "/funcionarios"
                f"?sucesso=Funcionário+{nome}+excluído+com+sucesso+dos+relógios+e+do+sistema."
            ),
            status_code=303
        )

    except HTTPException:

        db.rollback()
        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        db.close()


# ============================================================
# CADASTRAR FUNCIONÁRIO NOS RELÓGIOS
# ============================================================

@router.post(
    "/funcionarios/{funcionario_id}/cadastrar-relogios"
)
async def cadastrar_funcionario_relogios(
    funcionario_id: int,
    loja_id: int | None = None
):

    db: Session = SessionLocal()

    resultados = []

    try:

        # ----------------------------------------------------
        # FUNCIONÁRIO
        # ----------------------------------------------------

        funcionario = (
            db.query(Funcionario)
            .filter(
                Funcionario.id == funcionario_id
            )
            .first()
        )

        if not funcionario:

            raise HTTPException(
                status_code=404,
                detail="Funcionário não encontrado."
            )

        # ----------------------------------------------------
        # LOJAS ASSOCIADAS
        # ----------------------------------------------------

        relacionamentos = (
            db.query(FuncionarioLoja)
            .filter(
                FuncionarioLoja.funcionario_id
                == funcionario.id
            )
            .all()
        )

        if not relacionamentos:
            mensagem = "Funcionário não possui nenhuma empresa associada."
            url = "/funcionarios"
            if loja_id is not None:
                url += f"?loja_id={loja_id}&"
            else:
                url += "?"

            return RedirectResponse(
                url=url + "erro=" + quote_plus(mensagem),
                status_code=303
            )

        # ----------------------------------------------------
        # CADA RELÓGIO
        # ----------------------------------------------------

        for relacionamento in relacionamentos:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == relacionamento.loja_id
                )
                .first()
            )

            if not loja:
                continue

            equipamento = None

            try:

                # =================================================
                # DEFINIR MODO DO RELÓGIO
                # =================================================

                layout = (
                    loja.afd_layout or "legado"
                ).lower().strip()

                if layout in ("671", "portaria671"):

                    mode = 671

                    if not funcionario.cpf:

                        raise Exception(
                            "Funcionário não possui CPF "
                            "para o modo Portaria 671."
                        )

                    identificador_chave = "cpf"

                else:

                    mode = 0

                    if not funcionario.pis:

                        raise Exception(
                            "Funcionário não possui PIS "
                            "para o modo Legado."
                        )

                    identificador_chave = "pis"

                # =================================================
                # CONECTAR
                # =================================================

                equipamento = IDClass(
                    loja.ip,
                    username=loja.usuario or "admin",
                    password=loja.senha or "7070",
                    timeout=30
                )

                equipamento.login_device()

                # =================================================
                # CADASTRAR
                # =================================================

                resposta = equipamento.cadastrar_usuario(
                    nome=funcionario.nome,
                    matricula=funcionario.matricula,
                    cpf=funcionario.cpf,
                    pis=funcionario.pis,
                    admin=funcionario.administrador,
                    templates=(
                        json.loads(funcionario.biometrias)
                        if funcionario.biometrias
                        else None
                    ),
                    mode=mode
                )

                resultados.append({
                    "loja_id": loja.id,
                    "loja": loja.numero,
                    "nome": loja.nome,
                    "layout": layout,
                    "mode": mode,
                    "success": True,
                    "mensagem":
                        "Funcionário cadastrado com sucesso.",
                    "resposta": resposta
                })

            except Exception as e:

                resultados.append({
                    "loja_id": loja.id,
                    "loja": loja.numero,
                    "nome": loja.nome,
                    "layout":
                        loja.afd_layout or "legado",
                    "success": False,
                    "mensagem": str(e)
                })

            finally:

                if equipamento:

                    try:
                        equipamento.logout()
                    except Exception:
                        pass

        return {
            "success": all(
                resultado["success"]
                for resultado in resultados
            ),
            "funcionario_id": funcionario.id,
            "matricula": funcionario.matricula,
            "nome": funcionario.nome,
            "resultados": resultados
        }

    finally:

        db.close()
    
# ============================================================
# ATUALIZAR FUNCIONÁRIO NOS RELÓGIOS
# ============================================================

@router.post(
    "/funcionarios/{funcionario_id}/atualizar-relogios"
)
async def atualizar_funcionario_relogios(
    funcionario_id: int,
    loja_id: int | None = None
):

    db: Session = SessionLocal()

    resultados = []

    try:

        # ----------------------------------------------------
        # FUNCIONÁRIO
        # ----------------------------------------------------

        funcionario = (
            db.query(Funcionario)
            .filter(
                Funcionario.id == funcionario_id
            )
            .first()
        )

        if not funcionario:

            raise HTTPException(
                status_code=404,
                detail="Funcionário não encontrado."
            )

        # ----------------------------------------------------
        # LOJAS ASSOCIADAS
        # ----------------------------------------------------

        relacionamentos = (
            db.query(FuncionarioLoja)
            .filter(
                FuncionarioLoja.funcionario_id
                == funcionario.id
            )
            .all()
        )

        if not relacionamentos:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Funcionário não possui "
                    "nenhuma loja associada."
                )
            )

        # ----------------------------------------------------
        # ATUALIZAR CADA RELÓGIO
        # ----------------------------------------------------

        for relacionamento in relacionamentos:

            loja = (
                db.query(Loja)
                .filter(
                    Loja.id == relacionamento.loja_id
                )
                .first()
            )

            if not loja:
                continue

            equipamento = None

            try:

                layout = (
                    loja.afd_layout or "legado"
                ).lower().strip()

                # ------------------------------------------------
                # DEFINIR MODO
                # ------------------------------------------------

                if layout in ("671", "portaria671"):

                    mode = 671

                    if not funcionario.cpf:

                        raise Exception(
                            "Funcionário não possui CPF "
                            "para o modo Portaria 671."
                        )

                    identificador_chave = "cpf"

                else:

                    mode = 0

                    if not funcionario.pis:

                        raise Exception(
                            "Funcionário não possui PIS "
                            "para o modo Legado."
                        )

                    identificador_chave = "pis"

                # ------------------------------------------------
                # CONECTAR
                # ------------------------------------------------

                equipamento = IDClass(
                    loja.ip,
                    username=loja.usuario or "admin",
                    password=loja.senha or "7070",
                    timeout=30
                )

                equipamento.login_device()

                usuario_existente = equipamento.get_user_by_registration(
                    funcionario.matricula,
                    mode=mode
                )

                if usuario_existente:
                    identificador_relogio = usuario_existente.get(
                        identificador_chave
                    )
                    if identificador_relogio is not None:
                        if identificador_chave == "cpf":
                            funcionario.cpf = str(identificador_relogio)
                        else:
                            funcionario.pis = str(identificador_relogio)

                    for atributo, chave in (
                        ("codigo", "code"),
                        ("rfid", "rfid"),
                        ("bars", "bars"),
                    ):
                        valor = usuario_existente.get(chave)
                        if (
                            valor is not None
                            and str(valor).strip()
                            and _identificador_disponivel(
                                funcionario,
                                atributo,
                                valor
                            )
                        ):
                            setattr(funcionario, atributo, valor)

                _garantir_identificadores(funcionario)

                # ------------------------------------------------
                # ATUALIZAR
                # ------------------------------------------------

                resposta = equipamento.sincronizar_usuario(
                    nome=funcionario.nome,
                    matricula=funcionario.matricula,
                    cpf=funcionario.cpf,
                    pis=funcionario.pis,
                    codigo=funcionario.codigo,
                    rfid=funcionario.rfid,
                    bars=funcionario.bars,
                    admin=funcionario.administrador,
                    templates=(
                        json.loads(funcionario.biometrias)
                        if funcionario.biometrias
                        else None
                    ),
                    mode=mode
                )

                resultados.append({
                    "loja_id": loja.id,
                    "loja": loja.numero,
                    "nome": loja.nome,
                    "layout": layout,
                    "mode": mode,
                    "success": True,
                    "mensagem":
                        "Funcionário atualizado com sucesso.",
                    "resposta": resposta
                })

            except Exception as e:

                resultados.append({
                    "loja_id": loja.id,
                    "loja": loja.numero,
                    "nome": loja.nome,
                    "layout":
                        loja.afd_layout or "legado",
                    "success": False,
                    "mensagem": str(e)
                })

            finally:

                if equipamento:

                    try:
                        equipamento.logout()
                    except Exception:
                        pass

        sucesso = all(
            resultado["success"]
            for resultado in resultados
        )

        detalhes = " | ".join(
            f"Empresa {resultado['loja']:02d}: {resultado['mensagem']}"
            for resultado in resultados
            if not resultado["success"]
        )

        mensagem = (
            "Funcionário atualizado nos relógios."
            if sucesso
            else (
                "Falha ao atualizar o funcionário em uma ou mais empresas. "
                + detalhes
            )
        )

        url = "/funcionarios"
        if loja_id is not None:
            url += f"?loja_id={loja_id}"

        return RedirectResponse(
            url=url + ("&" if "?" in url else "?")
            + ("sucesso=" if sucesso else "erro=")
            + quote_plus(mensagem),
            status_code=303
        )

    except HTTPException as erro:
        mensagem = str(erro.detail)
        url = "/funcionarios"
        if loja_id is not None:
            url += f"?loja_id={loja_id}&"
        else:
            url += "?"

        return RedirectResponse(
            url=url + "erro=" + quote_plus(mensagem),
            status_code=303
        )

    finally:

        db.close()