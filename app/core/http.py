import time
import logging
import httpx
from typing import Any

logger = logging.getLogger("core.http")


def _crear_http_client() -> httpx.Client:
    def _log_request(request: httpx.Request) -> None:
        request.extensions["t_inicio"] = time.perf_counter()

    def _log_response(response: httpx.Response) -> None:
        t_fin = time.perf_counter()
        t_inicio = response.request.extensions.get("t_inicio", t_fin)
        t_total_http = t_fin - t_inicio

        t_procesamiento = response.headers.get("x-processing-time-ms")
        t_facturacion = response.headers.get("x-billing-duration-ms")

        extra = []
        if t_procesamiento:
            extra.append(f"procesamiento_servidor={float(t_procesamiento) / 1000:.2f}s")
        if t_facturacion:
            extra.append(f"facturacion_servidor={float(t_facturacion) / 1000:.2f}s")

        extra_str = " | " + " | ".join(extra) if extra else ""
        logger.info(
            "[HTTP] %s | status=%d | total_http=%.2fs%s",
            response.request.url.path, response.status_code, t_total_http, extra_str,
        )

    return httpx.Client(
        timeout=httpx.Timeout(30.0),
        event_hooks={"request": [_log_request], "response": [_log_response]},
    )


_http_client = _crear_http_client()


async def http_get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    t_inicio = time.perf_counter()
    logger.info("[HTTP] GET %s | params=%s", url, params)
    try:
        response = _http_client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        t_duracion = time.perf_counter() - t_inicio
        logger.info("[HTTP] GET %s | status=%d | duration=%.2fs", url, response.status_code, t_duracion)
        return data
    except httpx.HTTPStatusError as e:
        t_duracion = time.perf_counter() - t_inicio
        logger.error("[HTTP] GET %s | status=%d | error=%s | duration=%.2fs", url, e.response.status_code, str(e), t_duracion)
        raise
    except Exception as e:
        t_duracion = time.perf_counter() - t_inicio
        logger.error("[HTTP] GET %s | error=%s | duration=%.2fs", url, str(e), t_duracion)
        raise


async def http_post_json(url: str, json_data: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    t_inicio = time.perf_counter()
    logger.info("[HTTP] POST %s", url)
    try:
        response = _http_client.post(url, json=json_data, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        t_duracion = time.perf_counter() - t_inicio
        logger.info("[HTTP] POST %s | status=%d | duration=%.2fs", url, response.status_code, t_duracion)
        return data
    except httpx.HTTPStatusError as e:
        t_duracion = time.perf_counter() - t_inicio
        logger.error("[HTTP] POST %s | status=%d | error=%s | duration=%.2fs", url, e.response.status_code, str(e), t_duracion)
        raise
    except Exception as e:
        t_duracion = time.perf_counter() - t_inicio
        logger.error("[HTTP] POST %s | error=%s | duration=%.2fs", url, str(e), t_duracion)
        raise
