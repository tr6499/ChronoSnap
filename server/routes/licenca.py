from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from app_paths import APP_DIR

router = APIRouter(tags=["Licença"])
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
APP_VERSION = "1.0.4"
AUTHOR = "Tetsuo Rodolfo Okubo"
GNU_LICENSE_URL = "https://www.gnu.org/licenses/gpl-3.0.html"


@router.get("/licenca")
async def pagina_licenca(request: Request):
    license_path = next(
        (
            path
            for path in (
                APP_DIR.parent / "COPYING",
                APP_DIR.parent / "LICENSE.txt",
            )
            if path.is_file()
        ),
        None,
    )
    if license_path is None:
        raise HTTPException(
            status_code=500,
            detail="O texto da licença GNU GPL v3 não foi encontrado.",
        )

    try:
        license_text = license_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Não foi possível ler o texto da licença: {exc}",
        ) from exc

    return templates.TemplateResponse(
        request=request,
        name="licenca.html",
        context={
            "app_version": APP_VERSION,
            "author": AUTHOR,
            "gnu_license_url": GNU_LICENSE_URL,
            "license_text": license_text,
        },
    )
