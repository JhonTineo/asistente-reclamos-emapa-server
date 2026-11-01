import logging
from contextvars import ContextVar
from typing import Any, Optional
import httpx

from app.src.infrastructure.config.settings import settings
from app.src.infrastructure.adapters.http_client import http_get_json, http_post_json, EmapaSinDatosError
from app.src.application.ports.emapa_api_port import PuertoEmapaAPI

logger = logging.getLogger("tools.emapa_api")

# Token de EMAPA para la petición en curso.
emapa_token_ctx: ContextVar[Optional[str]] = ContextVar("emapa_token_ctx", default=None)

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
    "inspeccion_externa": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-externa/{codsuc}/{codinspeccion}",
        "method": "GET",
    },
    "inspeccion_interna": {
        "path": "/api-micromedicion/reclamos/get-inspeccion-interna/{codsuc}/{codinspeccion}",
        "method": "GET",
    },
    "imagenes_cliente": {
        "path": "/api-externa/ftp/generico/download/read",
        "method": "POST",
    },
    "buscar_reclamo": {
        "path": "/api-reclamos/reclamo/obtener/detalle/{codsede}/{codsuc}/{codreclamo}/{codcliente}",
        "method": "GET",
    },
}

class EmapaHttpAdapter(PuertoEmapaAPI):
    
    def set_token(self, token: Optional[str]) -> None:
        """Fija el token de EMAPA para la petición en curso."""
        if token and token.strip():
            emapa_token_ctx.set(token.strip())
            logger.info("[EMAPA] Token fijado en ContextVar (primeros 20 chars): %s…", token.strip()[:20])
        else:
            logger.warning("[EMAPA] set_emapa_token llamado con token vacío o None")
            
    def _get_url(self, path: str) -> str:
        return f"{settings.emapa_api_base_url}{path}"
        
    def _get_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
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
        
    def _request(self, path: str) -> dict[str, Any]:
        url = self._get_url(path)
        try:
            return http_get_json(
                url=url,
                headers=self._get_headers(),
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

    def buscar_reclamo(self, codsede: str, codsuc: str, codreclamo: str, codcliente: str) -> dict[str, Any]:
        endpoint = EMAPA_ENDPOINTS["buscar_reclamo"]["path"].format(
            codsede=codsede,
            codsuc=codsuc,
            codreclamo=codreclamo,
            codcliente=codcliente,
        )
        return self._request(endpoint)

    def obtener_saldo_actual(self, codsuc: str, codcliente: str) -> dict[str, Any]:
        endpoint = EMAPA_ENDPOINTS["saldo_actual"]["path"].format(
            codsuc=codsuc,
            codcliente=codcliente,
        )
        return self._request(endpoint)

    def obtener_tarjeta_lectura(self, codsuc: str, codcliente: str) -> dict[str, Any]:
        endpoint = EMAPA_ENDPOINTS["tarjeta_lectura"]["path"].format(
            codsuc=codsuc,
            codcliente=codcliente,
        )
        return self._request(endpoint)

    def obtener_record_facturacion(self, codsuc: str, codcliente: str, anio: str) -> dict[str, Any]:
        endpoint = EMAPA_ENDPOINTS["record_facturacion"]["path"].format(
            codsuc=codsuc,
            codcliente=codcliente,
            anio=anio,
        )
        return self._request(endpoint)

    def obtener_corte_reapertura(self, codsuc: str, codcliente: str) -> dict[str, Any]:
        endpoint = EMAPA_ENDPOINTS["corte_reapertura"]["path"].format(
            codsuc=codsuc,
            codcliente=codcliente,
        )
        return self._request(endpoint)

    def obtener_inspeccion_externa(self, codsuc: str, codinspeccion: str) -> dict[str, Any]:
        endpoint = EMAPA_ENDPOINTS["inspeccion_externa"]["path"].format(
            codsuc=codsuc,
            codinspeccion=codinspeccion,
        )
        return self._request(endpoint)

    def obtener_inspeccion_interna(self, codsuc: str, codinspeccion: str) -> dict[str, Any]:
        endpoint = EMAPA_ENDPOINTS["inspeccion_interna"]["path"].format(
            codsuc=codsuc,
            codinspeccion=codinspeccion,
        )
        return self._request(endpoint)

    def obtener_imagenes_cliente(self, codsuc: str, codcliente: str,
                                 fecha_inicial: str, fecha_final: str) -> dict[str, Any]:
        """POST ftp/generico/download/read. Devuelve las imágenes con su base64,
        por eso puede tardar (≈20 s para dos meses): timeout amplio y sin
        reintentos. Se prueba primero con 'Bearer <token>' (como el resto del
        adaptador) y, si SYSCO responde vacío o 401/403, con el token crudo
        (así lo acepta api-externa en las pruebas realizadas)."""
        url = self._get_url(EMAPA_ENDPOINTS["imagenes_cliente"]["path"])
        cuerpo = {"codsuc": codsuc, "codcliente": int(codcliente) if str(codcliente).isdigit() else codcliente,
                  "fecha_inicial": fecha_inicial, "fecha_final": fecha_final}
        headers = self._get_headers()
        intentos = [headers]
        auth = headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            intentos.append({**headers, "Authorization": auth[7:]})
        ultimo: Exception | None = None
        for h in intentos:
            try:
                return http_post_json(url=url, json_data=cuerpo, headers=h, timeout=120.0, retries=0)
            except EmapaSinDatosError as exc:
                ultimo = exc
            except httpx.HTTPStatusError as exc:
                if exc.response is None or exc.response.status_code not in (401, 403):
                    raise
                ultimo = exc
        if isinstance(ultimo, EmapaSinDatosError):
            return {"data": []}
        raise ultimo  # type: ignore[misc]
