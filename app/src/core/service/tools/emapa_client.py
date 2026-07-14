import httpx
import logging
from app.src.core.service.tools.base import Tool, ToolResult
from app.src.application.adapters.emapa_config import EMAPA_API_BASE_URL, EMAPA_ENDPOINTS, EMAPA_ACCESS_TOKEN
from app.src.application.adapters.config import settings
from app.src.core.service.tools.emapa_api import emapa_token_ctx

logger = logging.getLogger("tools.emapa_client")


def consultar_emapa(endpoint_key: str, params: dict) -> ToolResult:
    """Consulta un endpoint genérico de EMAPA."""
    try:
        endpoint_config = EMAPA_ENDPOINTS.get(endpoint_key)
        if not endpoint_config:
            logger.error("[EMAPA_CLIENT] Endpoint no encontrado: %s", endpoint_key)
            return ToolResult(
                success=False,
                error=f"Endpoint '{endpoint_key}' no encontrado"
            )

        path = endpoint_config["path"]
        path_original = path

        for key, value in params.items():
            placeholder = f"{{{key}}}"
            if placeholder in path:
                path = path.replace(placeholder, str(value))
            else:
                logger.warning("[EMAPA_CLIENT] Parametro %s no encontrado en path", key)

        url = f"{EMAPA_API_BASE_URL}{path}"
        # Prioridad: token de la petición (ContextVar) y, si no vino, el de .env.
        token = emapa_token_ctx.get() or settings.emapa_access_token or EMAPA_ACCESS_TOKEN

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        response = httpx.get(url, headers=headers, timeout=10.0)

        logger.info("[EMAPA_CLIENT] RESPONSE | status=%d | size=%d", response.status_code, len(response.text))

        if response.status_code >= 400:
            logger.error("[EMAPA_CLIENT] ERROR HTTP | status=%d | body=%s",
                        response.status_code, response.text[:500])
            return ToolResult(
                success=False,
                error=f"Error HTTP {response.status_code}: {response.text[:200]}"
            )

        text = response.text.strip()

        if not text:
            logger.warning("[EMAPA_CLIENT] Respuesta vacía")
            return ToolResult(success=True, data='{"status": "empty", "message": "Respuesta vacía del servidor"}')

        import json
        try:
            data = json.loads(text)
            logger.info("[EMAPA_CLIENT] JSON parseado OK | keys=%s", list(data.keys()) if isinstance(data, dict) else "list")
            return ToolResult(success=True, data=json.dumps(data, indent=2))
        except json.JSONDecodeError as e:
            logger.warning("[EMAPA_CLIENT] Respuesta no es JSON, retornando como texto | error=%s", str(e))
            return ToolResult(success=True, data=text)

    except httpx.ConnectError as e:
        logger.error("[EMAPA_CLIENT] CONNECTION ERROR: %s", str(e))
        return ToolResult(success=False, error=f"Error de conexión: {str(e)}")
    except httpx.TimeoutException:
        logger.error("[EMAPA_CLIENT] TIMEOUT | endpoint=%s | No se obtuvo respuesta de los servicios", endpoint_key)
        return ToolResult(success=False, error="No se obtuvo respuesta de los servicios")
    except Exception as e:
        logger.error("[EMAPA_CLIENT] EXCEPTION | type=%s | error=%s", type(e).__name__, str(e))
        return ToolResult(success=False, error=str(e))
