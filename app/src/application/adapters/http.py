import time
import logging
import httpx
from typing import Any

from app.src.application.adapters.config import settings

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


def _request_json(
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    retries: int | None = None,
) -> dict[str, Any]:
    req_timeout = timeout if timeout is not None else float(settings.timeout_seconds)
    req_retries = retries if retries is not None else int(settings.max_retries)

    last_error: Exception | None = None

    for attempt in range(1, req_retries + 2):
        t_inicio = time.perf_counter()
        logger.info(
            "[HTTP] %s %s | attempt=%d/%d",
            method,
            url,
            attempt,
            req_retries + 1,
        )

        try:
            response = _http_client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=req_timeout,
            )
            response.raise_for_status()

            t_duracion = time.perf_counter() - t_inicio
            logger.info(
                "[HTTP] %s %s | status=%d | duration=%.2fs",
                method,
                url,
                response.status_code,
                t_duracion,
            )
            return response.json()

        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            last_error = exc
            t_duracion = time.perf_counter() - t_inicio
            logger.warning(
                "[HTTP] %s %s | attempt=%d failed | error=%s | duration=%.2fs",
                method,
                url,
                attempt,
                str(exc),
                t_duracion,
            )

            if attempt >= req_retries + 1:
                break

    logger.error("[HTTP] %s %s | agotados reintentos", method, url)
    if last_error:
        raise last_error
    raise RuntimeError("Fallo HTTP sin detalle")


def http_get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    retries: int | None = None,
) -> dict[str, Any]:
    return _request_json(
        method="GET",
        url=url,
        params=params,
        headers=headers,
        timeout=timeout,
        retries=retries,
    )


def http_post_json(
    url: str,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    retries: int | None = None,
) -> dict[str, Any]:
    return _request_json(
        method="POST",
        url=url,
        json_data=json_data,
        headers=headers,
        timeout=timeout,
        retries=retries,
    )
