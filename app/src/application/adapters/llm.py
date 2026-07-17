import time
import logging
import socket

import httpx
import os
from urllib.parse import urlsplit, urlunsplit

from langchain_ollama import ChatOllama

from app.src.application.adapters.config import settings

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
        num_ctx=4096
    )


def log_uso_llm(log: logging.Logger, etiqueta: str, response) -> None:
    """Loguea los tokens y la velocidad de una respuesta del LLM, usando los
    conteos reales que devuelve Ollama (tokenizer exacto del modelo).

    - input_tokens / output_tokens / total_tokens: de ``usage_metadata``.
    - tok/s: tokens de salida entre la duración de generación (``eval_duration``,
      que Ollama reporta en nanosegundos)."""
    usage = getattr(response, "usage_metadata", None) or {}
    meta = getattr(response, "response_metadata", None) or {}
    in_tok = usage.get("input_tokens") or meta.get("prompt_eval_count")
    out_tok = usage.get("output_tokens") or meta.get("eval_count")
    total = usage.get("total_tokens")
    if total is None and in_tok is not None and out_tok is not None:
        total = in_tok + out_tok

    extra = ""
    eval_dur = meta.get("eval_duration")  # nanosegundos
    if out_tok and eval_dur:
        tok_s = out_tok / (eval_dur / 1e9)
        extra = f" | {tok_s:.1f} tok/s"

    log.info("[TOKENS %s] input=%s output=%s total=%s%s", etiqueta, in_tok, out_tok, total, extra)


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


# Tiempo que el modelo queda residente en memoria sin recibir peticiones antes
# de que Ollama lo descargue por su cuenta (no hay temporizador propio aquí).
KEEP_ALIVE_INACTIVIDAD = "5m"


def modelos_cargados() -> list[str]:
    """Modelos actualmente residentes en memoria (RAM/VRAM) según Ollama."""
    ollama_url = _resolver_ollama_base_url().rstrip("/")
    endpoint = f"{ollama_url}/api/ps"
    try:
        response = httpx.get(endpoint, timeout=20.0)
        response.raise_for_status()
        payload = response.json()
        return [m.get("name") for m in payload.get("models", []) if m.get("name")]
    except Exception as exc:
        logger.warning("No se pudo consultar modelos cargados de Ollama: %s", exc)
        return []


def _set_keep_alive(model: str, keep_alive: str | int) -> dict:
    """Pide a Ollama cargar/descargar `model` sin generar tokens.

    Se omite la clave `prompt` (no se manda vacía) para que /api/generate solo
    cargue el modelo en memoria y responda de inmediato con done=true."""
    ollama_url = _resolver_ollama_base_url().rstrip("/")
    endpoint = f"{ollama_url}/api/generate"
    payload = {"model": model, "keep_alive": keep_alive}

    t_inicio = time.perf_counter()
    try:
        response = httpx.post(endpoint, json=payload, timeout=300.0)
        response.raise_for_status()
        data = response.json()
        tiempo = time.perf_counter() - t_inicio
        logger.info(
            "[OLLAMA] '%s' keep_alive=%s | done=%s | tiempo=%.2fs",
            model, keep_alive, data.get("done"), tiempo,
        )
        return {
            "modelo": model,
            "ok": bool(data.get("done")),
            "en_memoria": model in modelos_cargados(),
            "tiempo": tiempo,
        }
    except Exception as exc:
        logger.warning("[OLLAMA] Fallo keep_alive=%s para '%s': %s", keep_alive, model, exc)
        return {
            "modelo": model,
            "ok": False,
            "en_memoria": False,
            "tiempo": time.perf_counter() - t_inicio,
            "error": str(exc),
        }


def cargar_modelo(model: str) -> dict:
    """Precarga el modelo en memoria (keep_alive=5m). Ollama lo descarga solo
    tras 5 minutos de inactividad; no hay temporizador propio en el backend."""
    return _set_keep_alive(model, KEEP_ALIVE_INACTIVIDAD)


def descargar_modelo(model: str) -> dict:
    """Libera el modelo de memoria de inmediato (keep_alive=0)."""
    return _set_keep_alive(model, 0)
