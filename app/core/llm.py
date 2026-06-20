import time
import logging

import httpx
import os

from langchain_ollama import ChatOllama

from app.core.config import settings

logger = logging.getLogger("core.llm")


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
        timeout=httpx.Timeout(120.0),
        event_hooks={"request": [_log_request], "response": [_log_response]},
    )


_http_client = _crear_http_client()


def get_llm(model: str | None = None):
    return ChatOllama(
        model=model or os.getenv("OLLAMA_GENERATOR_MODEL", settings.ollama_generator_model),
        base_url=os.getenv("OLLAMA_BASE_URL", settings.ollama_base_url),
        temperature=0,
    )


def listar_modelos() -> list[str]:
    ollama_url = os.getenv("OLLAMA_BASE_URL", settings.ollama_base_url).rstrip("/")
    endpoint = f"{ollama_url}/api/tags"

    try:
        response = httpx.get(endpoint, timeout=20.0)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", [])
        return [m.get("name") for m in models if m.get("name")]
    except Exception as exc:
        logger.warning("No se pudo listar modelos de Ollama: %s", exc)
        return []
