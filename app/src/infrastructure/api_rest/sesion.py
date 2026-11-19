"""Sesión de EMAPA obligatoria para los endpoints con datos de reclamos.

El login lo hace el navegador directo contra SYSCO; el backend solo recibe el
JWT resultante en ``Authorization``. Para que nadie pueda leer la memoria de
reclamos (informes, evidencias, fotos…) sin haber iniciado sesión, toda
petición a esos routers debe traer un token que:

1. sea un JWT con ``exp`` vigente (chequeo local, sin red), y
2. SYSCO acepte (``seleccionar-sistema`` responde ``EXITO`` con ese token).

El resultado de (2) se guarda en memoria por un rato (por hash del token) para
no consultar a SYSCO en cada petición. Si SYSCO no responde, se rechaza (falla
cerrada), salvo que el token ya estuviera verificado en caché.
"""

import base64
import hashlib
import json
import logging
import time

import httpx
from fastapi import HTTPException, Request

from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter
from app.src.infrastructure.config.settings import settings

logger = logging.getLogger("api.sesion")

# Sistema "Comercial", el mismo que selecciona el front al iniciar sesión.
_RUTA_VERIFICACION = "/api-seguridad/sistemas/seleccionar-sistema/002"
_TTL_VALIDO = 15 * 60      # s que se confía en un token ya verificado
_TTL_INVALIDO = 60         # s que se recuerda un rechazo (evita martillar SYSCO)

_cache: dict[str, tuple[bool, float]] = {}

SESION_REQUERIDA = "Inicia sesión en EMAPA para continuar."
SESION_VENCIDA = "Tu sesión de EMAPA venció. Vuelve a iniciar sesión para continuar."


def _token_del_header(request: Request) -> str | None:
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth:
        return None
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else auth
    return token or None


def _exp_del_jwt(token: str) -> float | None:
    """``exp`` del JWT (sin verificar la firma: eso lo hace SYSCO). None si el
    token no tiene forma de JWT o no trae ``exp``."""
    partes = token.split(".")
    if len(partes) != 3:
        return None
    try:
        relleno = partes[1] + "=" * (-len(partes[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(relleno))
        exp = payload.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


async def _sysco_acepta(token: str) -> bool:
    url = f"{settings.emapa_api_base_url}{_RUTA_VERIFICACION}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as cliente:
            r = await cliente.get(url, headers={"Authorization": token, "Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.warning("[SESION] SYSCO no respondió al verificar el token: %s", exc)
        raise HTTPException(status_code=503, detail="No se pudo verificar la sesión con EMAPA. Intenta de nuevo.")
    if r.status_code in (401, 403):
        return False
    if r.status_code >= 500:
        logger.warning("[SESION] SYSCO respondió %s al verificar el token", r.status_code)
        raise HTTPException(status_code=503, detail="No se pudo verificar la sesión con EMAPA. Intenta de nuevo.")
    try:
        data = r.json()
    except ValueError:
        return False
    return r.status_code == 200 and isinstance(data, dict) and data.get("response") == "EXITO"


async def requerir_sesion_emapa(request: Request) -> str:
    """Dependencia de router: exige una sesión de EMAPA válida (401 si no) y
    fija el token para las consultas a SYSCO de esta petición."""
    token = _token_del_header(request)
    if not token:
        raise HTTPException(status_code=401, detail=SESION_REQUERIDA)

    exp = _exp_del_jwt(token)
    ahora = time.time()
    if exp is None or exp <= ahora:
        raise HTTPException(status_code=401, detail=SESION_VENCIDA)

    if settings.emapa_verificar_sesion:
        clave = hashlib.sha256(token.encode()).hexdigest()
        cacheado = _cache.get(clave)
        if cacheado and cacheado[1] > ahora:
            valido = cacheado[0]
        else:
            valido = await _sysco_acepta(token)
            vence = min(exp, ahora + _TTL_VALIDO) if valido else ahora + _TTL_INVALIDO
            _cache[clave] = (valido, vence)
            if len(_cache) > 2000:  # limpieza simple de entradas vencidas
                for k, (_, v) in list(_cache.items()):
                    if v <= ahora:
                        _cache.pop(k, None)
        if not valido:
            logger.info("[SESION] Token rechazado por SYSCO")
            raise HTTPException(status_code=401, detail=SESION_VENCIDA)

    EmapaHttpAdapter().set_token(token)
    return token
