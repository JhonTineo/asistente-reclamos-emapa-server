import httpx
import logging
from app.tools.base import Tool, ToolResult
from app.core.emapa_config import EMAPA_API_BASE_URL, EMAPA_ENDPOINTS, EMAPA_ACCESS_TOKEN
from app.core.config import settings

logger = logging.getLogger("tools.emapa_client")


class ConsultarMedioProbatorioTool(Tool):
    name = "consultar_medio_probatorio"
    description = "Consulta un medio probatorio de EMAPA."

    def execute(self, medio_id: str, **kwargs) -> ToolResult:
        try:
            endpoint_config = EMAPA_ENDPOINTS.get(medio_id)
            if not endpoint_config:
                logger.error("[EMAPA_CLIENT] Medio no encontrado: %s", medio_id)
                return ToolResult(
                    success=False,
                    error=f"Medio '{medio_id}' no encontrado"
                )

            path = endpoint_config["path"]
            params = kwargs.get("params", {})

            for key, value in params.items():
                path = path.replace(f"{{{key}}}", str(value))

            url = f"{EMAPA_API_BASE_URL}{path}"
            token = settings.emapa_access_token or EMAPA_ACCESS_TOKEN

            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            logger.info("[EMAPA_CLIENT] REQUEST | medio=%s | method=GET | url=%s", medio_id, url)
            logger.debug("[EMAPA_CLIENT] Headers: %s", headers)

            response = httpx.get(url, headers=headers, timeout=30.0)
            
            logger.info("[EMAPA_CLIENT] RESPONSE | medio=%s | status=%d | size=%d bytes",
                       medio_id, response.status_code, len(response.content))

            if response.status_code >= 400:
                logger.error("[EMAPA_CLIENT] ERROR | medio=%s | status=%d | body=%s",
                           medio_id, response.status_code, response.text[:200])

            response.raise_for_status()

            return ToolResult(success=True, data=response.text)

        except httpx.HTTPStatusError as e:
            logger.error("[EMAPA_CLIENT] HTTP ERROR | medio=%s | status=%d | message=%s",
                       medio_id, e.response.status_code, str(e))
            return ToolResult(
                success=False,
                error=f"Error HTTP {e.response.status_code}: {str(e)}"
            )
        except Exception as e:
            logger.error("[EMAPA_CLIENT] EXCEPTION | medio=%s | type=%s | message=%s",
                       medio_id, type(e).__name__, str(e))
            return ToolResult(success=False, error=str(e))


consultar_medio_probatorio = ConsultarMedioProbatorioTool()


def consultar_emapa(endpoint_key: str, params: dict) -> ToolResult:
    """
    Consulta un endpoint genérico de EMAPA.
    """
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
        token = settings.emapa_access_token or EMAPA_ACCESS_TOKEN

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        logger.info("[EMAPA_CLIENT] REQUEST | endpoint=%s", endpoint_key)
        logger.info("[EMAPA_CLIENT] URL=%s", url)
        logger.info("[EMAPA_CLIENT] HEADERS=%s", headers)

        response = httpx.get(url, headers=headers, timeout=30.0)

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
    except Exception as e:
        logger.error("[EMAPA_CLIENT] EXCEPTION | type=%s | error=%s", type(e).__name__, str(e))
        return ToolResult(success=False, error=str(e))
