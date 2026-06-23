import time
import logging
import socket

import httpx
import os
from urllib.parse import urlsplit, urlunsplit

from langchain_ollama import ChatOllama

from app.src.core.config import settings

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


def _resolver_ollama_base_url() -> str:
    """
    Resuelve la URL base de Ollama para modo local y contenedor.
    Si el host configurado no tiene resolución DNS (p.ej. "ollama" fuera de Docker),
    intenta fallback a localhost para desarrollo local.
    """
    base_url = os.getenv("OLLAMA_BASE_URL", settings.ollama_base_url)
    parsed = urlsplit(base_url)

    hostname = parsed.hostname
    if not hostname:
        return base_url

    try:
        socket.getaddrinfo(hostname, parsed.port or 80)
        return base_url
    except socket.gaierror:
        if hostname != "ollama":
            return base_url

        fallback_netloc = "127.0.0.1"
        if parsed.port:
            fallback_netloc = f"127.0.0.1:{parsed.port}"

        fallback_url = urlunsplit((parsed.scheme or "http", fallback_netloc, parsed.path, parsed.query, parsed.fragment))
        logger.warning(
            "OLLAMA_BASE_URL=%s no resolvible en este entorno. Usando fallback local %s",
            base_url,
            fallback_url,
        )
        return fallback_url


def _resolver_modelo(model: str | None = None) -> str:
    desired_model = model or os.getenv("OLLAMA_GENERATOR_MODEL", settings.ollama_generator_model)
    disponibles = listar_modelos()

    if not disponibles:
        return desired_model

    if desired_model in disponibles:
        return desired_model

    logger.warning(
        "Modelo configurado '%s' no disponible. Usando modelo detectado '%s'. Disponibles=%s",
        desired_model,
        disponibles[0],
        disponibles,
    )
    return disponibles[0]


def get_llm(model: str | None = None):
    return ChatOllama(
        model=_resolver_modelo(model),
        base_url=_resolver_ollama_base_url(),
        temperature=0,
        num_ctx=16384
    )


def listar_modelos() -> list[str]:
    ollama_url = _resolver_ollama_base_url().rstrip("/")
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
