from fastapi import APIRouter, HTTPException

from services.idclass import IDClass


router = APIRouter(
    prefix="/users",
    tags=["Usuários"]
)


@router.get("/count")
def count_users(ip: str):

    equipamento = IDClass(ip)
    try:
        equipamento.login_device()

        quantidade = equipamento.count_users()

        return {
            "success": True,
            "count": quantidade
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    finally:
        equipamento.logout()


@router.get("/")
def load_users(
    ip: str,
    offset: int = 0,
    limit: int = 100
):

    equipamento = IDClass(ip)
    try:
        equipamento.login_device()

        resultado = equipamento.load_users(
            offset=offset,
            limit=limit
        )

        return {
            "success": True,
            **resultado
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    finally:
        equipamento.logout()


@router.get("/all")
def load_all_users(ip: str):

    equipamento = IDClass(ip)
    try:
        equipamento.login_device()

        usuarios = equipamento.load_all_users()

        return {
            "success": True,
            "count": len(usuarios),
            "users": usuarios
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    finally:
        equipamento.logout()


@router.get("/registration/{registration}")
def get_user_by_registration(
    registration: int,
    ip: str
):

    equipamento = IDClass(ip)
    try:
        equipamento.login_device()

        usuario = equipamento.get_user_by_registration(
            registration
        )

        if usuario is None:
            raise HTTPException(
                status_code=404,
                detail="Usuário não encontrado"
            )

        return {
            "success": True,
            "user": usuario
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    finally:
        equipamento.logout()


@router.get("/code/{code}")
def get_user_by_code(
    code: int,
    ip: str
):

    equipamento = IDClass(ip)
    try:
        equipamento.login_device()

        usuario = equipamento.get_user_by_code(
            code
        )

        if usuario is None:
            raise HTTPException(
                status_code=404,
                detail="Usuário não encontrado"
            )

        return {
            "success": True,
            "user": usuario
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
    finally:
        equipamento.logout()