from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Loja
from services.monitor import estado_atual_loja
from services.users_sync import sincronizar_usuarios


BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

router = APIRouter()


# ============================================================
# LISTAR LOJAS
# ============================================================

@router.get("/lojas")
async def lojas_page(request: Request):

    db: Session = SessionLocal()

    try:

        lojas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )
        status_por_loja = {
            loja.id: estado_atual_loja(loja)
            for loja in lojas
        }

        return templates.TemplateResponse(
            request=request,
            name="lojas.html",
            context={
                "lojas": lojas,
                "status_por_loja": status_por_loja,
                "status_online": sum(
                    estado == "online"
                    for estado in status_por_loja.values()
                ),
                "status_offline": sum(
                    estado == "offline"
                    for estado in status_por_loja.values()
                ),
                "status_atencao": sum(
                    estado in (
                        "error",
                        "timeout",
                        "unknown",
                        "stale"
                    )
                    for estado in status_por_loja.values()
                )
            }
        )

    finally:
        db.close()


# ============================================================
# CADASTRAR / ATUALIZAR LOJA
# ============================================================

@router.post("/lojas")
async def adicionar_loja(
    numero: int = Form(...),
    nome: str = Form(...),
    ip: str = Form(...),
    porta: int = Form(443),
    usuario: str = Form(""),
    senha: str = Form(""),
    afd_layout: str = Form("legado")
):

    if afd_layout not in ("legado", "671"):
        afd_layout = "legado"

    db: Session = SessionLocal()

    try:

        loja_existente = (
            db.query(Loja)
            .filter(Loja.numero == numero)
            .first()
        )

        if loja_existente:

            loja_existente.nome = nome
            loja_existente.ip = ip
            loja_existente.porta = porta
            loja_existente.usuario = usuario
            loja_existente.senha = senha
            loja_existente.afd_layout = afd_layout
            loja_salva = loja_existente

        else:

            loja = Loja(
                numero=numero,
                nome=nome,
                ip=ip,
                porta=porta,
                usuario=usuario,
                senha=senha,
                afd_layout=afd_layout
            )

            db.add(loja)
            db.flush()
            loja_salva = loja

        db.commit()

        try:

            resultado = sincronizar_usuarios(
                loja_salva.id
            )

        except Exception as e:

            return RedirectResponse(
                url=(
                    "/lojas?erro=Loja salva, mas a "
                    "sincronização falhou: "
                    f"{e}"
                ),
                status_code=303
            )

    finally:
        db.close()

    return RedirectResponse(
        url=(
            "/lojas?sucesso=Loja salva e sincronizada. "
            f"{resultado['funcionarios_criados']} funcionário(s) "
            "novo(s) importado(s)."
        ),
        status_code=303
    )


# ============================================================
# EXCLUIR LOJA
# ============================================================

@router.post("/lojas/{loja_id}/excluir")
async def excluir_loja(loja_id: int):

    db: Session = SessionLocal()

    try:

        loja = (
            db.query(Loja)
            .filter(Loja.id == loja_id)
            .first()
        )

        if not loja:
            raise HTTPException(
                status_code=404,
                detail="Loja não encontrada"
            )

        db.delete(loja)
        db.commit()

    except Exception:

        db.rollback()
        raise

    finally:
        db.close()

    return RedirectResponse(
        url="/lojas",
        status_code=303
    )


# ============================================================
# SINCRONIZAR USUÁRIOS
# ============================================================

@router.post("/lojas/{loja_id}/sincronizar-usuarios")
async def sincronizar_usuarios_loja(
    loja_id: int
):

    try:

        resultado = sincronizar_usuarios(loja_id)

        return RedirectResponse(
            url=(
                "/lojas?sucesso=Sincronização concluída. "
                f"{resultado['funcionarios_criados']} funcionário(s) "
                "novo(s) importado(s)."
            ),
            status_code=303
        )

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.post("/lojas/sincronizar-usuarios/todas")
async def sincronizar_usuarios_todas_lojas():

    db: Session = SessionLocal()

    try:

        lojas = (
            db.query(Loja)
            .order_by(Loja.numero)
            .all()
        )

    finally:

        db.close()

    sincronizadas = 0
    falhas = []
    funcionarios_criados = 0

    for loja in lojas:

        try:

            resultado = sincronizar_usuarios(
                loja.id
            )

            sincronizadas += 1
            funcionarios_criados += resultado.get(
                "funcionarios_criados",
                0
            )

        except Exception:

            falhas.append(
                str(loja.numero).zfill(2)
            )

    mensagem = (
        f"Sincronização concluída: {sincronizadas} "
        "empresa(s) sincronizada(s), "
        f"{funcionarios_criados} funcionário(s) novo(s)."
    )

    if falhas:

        mensagem += (
            " Falha nas empresas: "
            + ", ".join(falhas)
            + "."
        )

    return RedirectResponse(
        url="/lojas?sucesso=" + quote_plus(mensagem),
        status_code=303
    )