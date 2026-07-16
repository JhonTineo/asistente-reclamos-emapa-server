"""Dependencias comunes para los endpoints REST."""

import logging

from fastapi import Request, HTTPException

from app.src.application.adapters.emapa_api import set_emapa_token, emapa_token_ctx
from app.src.application.services.informe.informe_store import informe_store

logger = logging.getLogger("api.deps")


async def usar_token_emapa(request: Request) -> None:
    """Fija, para la petición en curso, el token de EMAPA tomado del header
    ``Authorization``. Si la petición no trae token, no se fija nada y las
    consultas a EMAPA usan el token de ``.env`` (settings.emapa_access_token).

    Acepta tanto ``Authorization: Bearer <token>`` como el token "pelado".

    IMPORTANTE: esta dependencia debe ser ``async def`` para que se ejecute
    en el mismo event-loop que el endpoint y los cambios al ContextVar
    sean visibles en toda la cadena de llamadas.
    """
    auth = request.headers.get("Authorization")
    logger.info("[AUTH] Header Authorization recibido: %s", f"{auth[:30]}…" if auth else None)
    if not auth or not auth.strip():
        logger.info("[AUTH] Petición sin token; se usará el token de .env")
        return

    auth = auth.strip()
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else auth
    logger.info("[AUTH] Token parseado (primeros 20 chars): %s…", token[:20])
    set_emapa_token(token)


async def requerir_token_emapa(request: Request) -> str:
    """Como ``usar_token_emapa`` pero OBLIGATORIO: si la petición no trae token
    responde 401. Se usa en la búsqueda del reclamo, que es el punto de entrada
    del flujo y con cuyo token se harán los pasos siguientes.

    Devuelve el token para que el endpoint lo guarde asociado al reclamo.
    """
    await usar_token_emapa(request)  # idempotente: fija el ContextVar si vino
    token = emapa_token_ctx.get()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Falta el token de EMAPA en el header Authorization.",
        )
    return token


async def asegurar_token_emapa(codreclamo: str) -> None:
    """Garantiza que haya token para las consultas a EMAPA de este reclamo.

    Si la petición trajo token (ContextVar ya fijado por ``usar_token_emapa``),
    se respeta. Si no, se recupera el token guardado al buscar el reclamo. Si
    tampoco existe, las consultas usarán el token de ``.env``.
    """
    if emapa_token_ctx.get():
        return
    token = informe_store.obtener_token(codreclamo)
    if token:
        set_emapa_token(token)
        logger.debug("[AUTH] Token recuperado del store para reclamo %s", codreclamo)
    else:
        logger.debug("[AUTH] Sin token guardado para reclamo %s; se usará .env", codreclamo)

