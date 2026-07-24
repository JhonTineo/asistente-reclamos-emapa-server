import logging
from contextvars import ContextVar
from typing import Any
import httpx

from app.src.application.adapters.config import settings
from app.src.application.adapters.http import http_get_json

logger = logging.getLogger("tools.emapa_api")

# Token de EMAPA para la petición en curso. Lo fija la capa de API a partir
# del header Authorization; si queda vacío se usa el de .env (settings).
# Se usa ContextVar para que el token viaje por toda la cadena
# (endpoint -> agente -> servicios -> _request) sin pasarlo en cada firma,
# y sin filtrarse entre peticiones concurrentes.
emapa_token_ctx: ContextVar[str | None] = ContextVar("emapa_token_ctx", default=None)


def set_emapa_token(token: str | None) -> None:
    """Fija el token de EMAPA para la petición en curso (solo si viene)."""
    if token and token.strip():
        emapa_token_ctx.set(token.strip())
        logger.info("[EMAPA] Token fijado en ContextVar (primeros 20 chars): %s…", token.strip()[:20])
    else:
        logger.warning("[EMAPA] set_emapa_token llamado con token vacío o None")


EMAPA_ENDPOINTS = {
    "saldo_actual": {
        "path": "/api-caja/cobranza/obtener-saldo-detalle-x-cliente/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "tarjeta_lectura": {
        "path": "/api-micromedicion/customer-reading/get-customer-card/info/{codsuc}/{codcliente}",
        "method": "GET",
    },
    "record_facturacion": {
        "path": "/api-consulta/facturacion/obtener-record-facturacion-x-cliente-anio/{codsuc}/{codcliente}/{anio}",
        "method": "GET",
    },
    "corte_reapertura": {
        "path": "/api-consulta/catastro/obtener-corte-reapertura-x-cliente/{codsuc}/{codcliente}",
        "method": "GET",
    },
    # OJO: pese al nombre del path, EMAPA filtra estos dos por NÚMERO DE
    # INSPECCIÓN (nroinspeccion), no por cliente. Pasarle el código de
    # suministro/cliente devuelve una inspección de OTRO cliente por
    # coincidencia numérica (confirmado: nroinspeccion en la respuesta coincide
    # con lo enviado, pero codcliente/reclamante/fecha no tienen relación).
    "inspeccion_externa": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-externa/{codsuc}/{codinspeccion}",
        "method": "GET",
    },
    "inspeccion_interna": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-interna/{codsuc}/{codinspeccion}",
        "method": "GET",
    },
    "buscar_reclamo": {
        "path": "/api-reclamos/reclamo/obtener/detalle/{codsede}/{codsuc}/{codreclamo}/{codcliente}",
        "method": "GET",
    },
}


def _get_url(path: str) -> str:
    return f"{settings.emapa_api_base_url}{path}"


def _get_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    # Prioridad: token de la petición (ContextVar) y, si no vino, el de .env.
    ctx_token = emapa_token_ctx.get()
    env_token = settings.emapa_access_token
    token = ctx_token or env_token
    logger.info(
        "[EMAPA] _get_headers → ctx_token=%s | env_token=%s | usando=%s",
        f"{ctx_token[:20]}…" if ctx_token else None,
        f"{env_token[:20]}…" if env_token else None,
        "ctx" if ctx_token else ("env" if env_token else "NINGUNO"),
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        logger.error("[EMAPA] ¡SIN TOKEN! La petición irá sin Authorization header")
    return headers


def _request(path: str) -> dict[str, Any]:
    url = _get_url(path)
    try:
        return http_get_json(
            url=url,
            headers=_get_headers(),
            timeout=float(settings.timeout_seconds),
            retries=int(settings.max_retries),
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            logger.warning(
                "[EMAPA] Endpoint no encontrado (404). Continuando con datos parciales. url=%s",
                url,
            )
            return {
                "_partial": True,
                "_error": "endpoint_not_found",
                "_status_code": 404,
                "_url": url,
                "data": {},
            }
        raise


def buscar_reclamo_emapa(codsede: str, codsuc: str, codreclamo: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["buscar_reclamo"]["path"].format(
        codsede=codsede,
        codsuc=codsuc,
        codreclamo=codreclamo,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_saldo_actual(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["saldo_actual"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_tarjeta_lectura(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["tarjeta_lectura"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_record_facturacion(codsuc: str, codcliente: str, anio: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["record_facturacion"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
        anio=anio,
    )
    return _request(endpoint)


def obtener_corte_reapertura(codsuc: str, codcliente: str) -> dict[str, Any]:
    endpoint = EMAPA_ENDPOINTS["corte_reapertura"]["path"].format(
        codsuc=codsuc,
        codcliente=codcliente,
    )
    return _request(endpoint)


def obtener_inspeccion_externa(codsuc: str, codinspeccion: str) -> dict[str, Any]:
    """`codinspeccion` es el nroinspeccion (NO el código de cliente/suministro):
    este endpoint filtra por número de inspección. Ver el comentario en
    EMAPA_ENDPOINTS['inspeccion_externa']."""
    endpoint = EMAPA_ENDPOINTS["inspeccion_externa"]["path"].format(
        codsuc=codsuc,
        codinspeccion=codinspeccion,
    )
    return _request(endpoint)


def obtener_inspeccion_interna(codsuc: str, codinspeccion: str) -> dict[str, Any]:
    """`codinspeccion` es el nroinspeccion (NO el código de cliente/suministro):
    este endpoint filtra por número de inspección. Ver el comentario en
    EMAPA_ENDPOINTS['inspeccion_interna']."""
    endpoint = EMAPA_ENDPOINTS["inspeccion_interna"]["path"].format(
        codsuc=codsuc,
        codinspeccion=codinspeccion,
    )
    return _request(endpoint)
