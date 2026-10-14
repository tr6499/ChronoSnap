from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from database import SessionLocal
from models import Loja
from services.idclass import IDClass


router = APIRouter(
    prefix="/company",
    tags=["Company"]
)

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _obter_loja(db, loja_id):
    loja = db.query(Loja).filter(Loja.id == loja_id).first()
    if not loja:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return loja


def _equipamento(loja):
    return IDClass(
        ip=loja.ip,
        port=loja.porta or 443,
        username=loja.usuario or "admin",
        password=loja.senha or "7070"
    )


def _numero_opcional(valor, campo):
    valor = str(valor or "").strip()
    if not valor:
        return None
    if not valor.isdigit():
        raise HTTPException(
            status_code=400,
            detail=f"{campo} deve conter apenas números"
        )
    return int(valor)


def _documento(valor, tipo_doc):
    # O equipamento exige o CPF/CNPJ como número, sem máscara.
    digitos = "".join(char for char in str(valor or "") if char.isdigit())
    if not digitos:
        raise HTTPException(status_code=400, detail="CPF/CNPJ é obrigatório")
    tamanho_esperado = 11 if tipo_doc == 2 else 14
    if len(digitos) != tamanho_esperado:
        raise HTTPException(
            status_code=400,
            detail=f"CPF/CNPJ deve ter {tamanho_esperado} dígitos"
        )
    return int(digitos)


@router.get("/editar/{loja_id}")
async def editar_empresa_page(request: Request, loja_id: int):
    db = SessionLocal()

    try:
        loja = _obter_loja(db, loja_id)
        return templates.TemplateResponse(
            request=request,
            name="empresa.html",
            context={"loja": loja, "empresa": {}}
        )
    except HTTPException:
        raise
    finally:
        db.close()


@router.get("/novo")
async def nova_empresa_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="empresa.html",
        context={
            "loja": None,
            "empresa": {},
            "novo": True
        }
    )


@router.post("/novo")
async def criar_empresa(
    request: Request,
    numero: int = Form(...),
    loja_nome: str = Form(...),
    ip: str = Form(...),
    porta: int = Form(443),
    usuario: str = Form(""),
    senha: str = Form(""),
    afd_layout: str = Form("legado"),
    name: str = Form(...),
    address: str = Form(""),
    tipo_doc: int = Form(...),
    cpf_cnpj: str = Form(""),
    cei: str = Form(""),
    cpf: str = Form("")
):
    db = SessionLocal()
    equipamento = None

    try:
        if tipo_doc not in (1, 2):
            raise HTTPException(status_code=400, detail="Tipo de documento inválido")
        if afd_layout not in ("legado", "671"):
            raise HTTPException(status_code=400, detail="Layout AFD inválido")
        if db.query(Loja).filter(Loja.numero == numero).first():
            raise HTTPException(status_code=400, detail="Já existe uma empresa com esse número")

        empresa = {
            "name": name.strip(),
            "address": address.strip(),
            "tipo_doc": tipo_doc,
            "cpf_cnpj": _documento(cpf_cnpj, tipo_doc),
            "cei": _numero_opcional(cei, "CEI/CAEPF/CNO"),
            "cpf": _numero_opcional(cpf, "CPF do responsável")
        }
        equipamento = IDClass(
            ip=ip.strip(),
            port=porta or 443,
            username=usuario.strip() or "admin",
            password=senha.strip() or "7070"
        )
        equipamento.login_device()

        equipamento.edit_company(empresa)

        loja = Loja(
            numero=numero,
            nome=loja_nome.strip(),
            ip=ip.strip(),
            porta=porta or 443,
            usuario=usuario.strip() or "admin",
            senha=senha.strip() or "7070",
            afd_layout=afd_layout
        )
        db.add(loja)
        db.commit()
        return RedirectResponse(
            url=f"/lojas?sucesso=Empresa adicionada com sucesso.",
            status_code=303
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as erro:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="empresa.html",
            context={
                "loja": None,
                "empresa": {},
                "novo": True,
                "erro": f"Não foi possível adicionar a empresa: {erro}"
            },
            status_code=200
        )
    finally:
        if equipamento:
            try:
                equipamento.logout()
            except Exception:
                pass
        db.close()


@router.post("/editar/{loja_id}")
async def salvar_empresa(
    request: Request,
    loja_id: int,
    loja_nome: str = Form(...),
    ip: str = Form(...),
    porta: int = Form(443),
    usuario: str = Form(""),
    senha: str = Form(""),
    afd_layout: str = Form("legado"),
    acao: str = Form("salvar"),
    name: str = Form(""),
    address: str = Form(""),
    tipo_doc: int = Form(0),
    cpf_cnpj: str = Form(""),
    cei: str = Form(""),
    cpf: str = Form("")
):
    if afd_layout not in ("legado", "671"):
        raise HTTPException(status_code=400, detail="Layout AFD inválido")
    # Nome do empregador e tipo de documento só são obrigatórios
    # quando a ação realmente grava dados no relógio.
    if acao == "salvar" and tipo_doc not in (1, 2):
        raise HTTPException(status_code=400, detail="Tipo de documento inválido")

    db = SessionLocal()
    equipamento = None

    try:
        loja = _obter_loja(db, loja_id)

        ip_novo = ip.strip()
        usuario_novo = usuario.strip() or loja.usuario or "admin"
        senha_nova = senha.strip() or loja.senha or "7070"

        # Permite corrigir IP/usuário/senha salvos sem exigir
        # login bem-sucedido no relógio (útil quando os dados
        # salvos estão incorretos e impedem qualquer conexão).
        if acao == "salvar_conexao":
            loja.nome = loja_nome.strip()
            loja.ip = ip_novo
            loja.porta = porta or 443
            loja.usuario = usuario_novo
            loja.senha = senha_nova
            loja.afd_layout = afd_layout
            db.commit()
            return RedirectResponse(
                url=f"/company/editar/{loja.id}?sucesso=Dados de conexão salvos.",
                status_code=303
            )

        equipamento = IDClass(
            ip=ip_novo,
            port=porta or 443,
            username=usuario_novo,
            password=senha_nova
        )
        equipamento.login_device()

        if acao == "carregar":
            resposta = equipamento.get_company()
            loja.nome = loja_nome.strip()
            loja.ip = ip_novo
            loja.porta = porta or 443
            loja.usuario = usuario_novo
            loja.afd_layout = afd_layout
            return templates.TemplateResponse(
                request=request,
                name="empresa.html",
                context={
                    "loja": loja,
                    "empresa": resposta.get("company", resposta),
                    "sucesso": "Dados carregados do relógio."
                }
            )

        equipamento.edit_company({
            "name": name.strip(),
            "address": address.strip(),
            "tipo_doc": tipo_doc,
            "cpf_cnpj": _documento(cpf_cnpj, tipo_doc),
            "cei": _numero_opcional(cei, "CEI/CAEPF/CNO"),
            "cpf": _numero_opcional(cpf, "CPF do responsável")
        })

        loja.nome = loja_nome.strip()
        loja.ip = ip_novo
        loja.porta = porta or 443
        loja.usuario = usuario_novo
        loja.senha = senha_nova
        loja.afd_layout = afd_layout
        db.commit()

        return RedirectResponse(
            url=f"/empresa/editar/{loja.id}?sucesso=Empregador atualizado no relógio.",
            status_code=303
        )
    except HTTPException:
        raise
    except Exception as erro:
        db.rollback()
        return RedirectResponse(
            url=(
                f"/company/editar/{loja_id}"
                f"?erro=Falha ao atualizar o empregador: {erro}"
            ),
            status_code=303
        )
    finally:
        if equipamento:
            try:
                equipamento.logout()
            except Exception:
                pass
        db.close()


@router.get("/{numero}")
async def get_company(numero: int):

    db = SessionLocal()

    try:

        loja = (
            db.query(Loja)
            .filter(Loja.numero == numero)
            .first()
        )

        if not loja:
            raise HTTPException(
                status_code=404,
                detail="Loja não encontrada"
            )

        equipamento = IDClass(
            ip=loja.ip,
            username=loja.usuario or "admin",
            password=loja.senha or "7070"
        )

        equipamento.login_device()

        return equipamento.get_company()

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:

        db.close()

