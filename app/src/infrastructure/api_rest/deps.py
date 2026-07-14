"""Dependencias comunes para los endpoints REST."""

import logging

from fastapi import Request

from app.src.core.service.tools.emapa_api import set_emapa_token

logger = logging.getLogger("api.deps")


def usar_token_emapa(request: Request) -> None:
    """Fija, para la petición en curso, el token de EMAPA tomado del header
    ``Authorization``. Si la petición no trae token, no se fija nada y las
    consultas a EMAPA usan el token de ``.env`` (settings.emapa_access_token).

    Acepta tanto ``Authorization: Bearer <token>`` como el token "pelado".
    """
    auth = request.headers.get("Authorization")
    if not auth or not auth.strip():
        logger.debug("[AUTH] Petición sin token; se usará el token de .env")
        return

    auth = auth.strip()
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else auth
    set_emapa_token(token)
    logger.debug("[AUTH] Token de EMAPA tomado del header de la petición")
