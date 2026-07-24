import time
import logging
import socket

import httpx
import os
from urllib.parse import urlsplit, urlunsplit

from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.src.application.adapters.config import settings
from app.src.application.adapters.proveedores import (
    Proveedor,
    proveedores_externos,
    proveedor_por_id,
    get_llm_ctx,
)
from app.src.application.adapters.hardware import hardware_apto_para_local

logger = logging.getLogger("core.llm")


class ModeloNoCargadoError(RuntimeError):
    """No hay ningún modelo de chat cargado en memoria de Ollama. El llamador
    debe encender un modelo (POST /modelos/cargar) antes de continuar."""


class InferenciaLocalNoDisponibleError(RuntimeError):
    """El servidor no cumple los requisitos para ofrecer inferencia LOCAL de
    chat (hardware insuficiente, Ollama sin conexión, o sin modelos de chat
    descargados). No aplica a embeddings, que siguen corriendo en Ollama local
    sin este chequeo."""


def _catalogo_externo() -> dict[str, Proveedor]:
    """Mapa modelo_id -> Proveedor (primer proveedor que declara el modelo)."""
    cat: dict[str, Proveedor] = {}
    for p in proveedores_externos():
        for m in p.modelos:
            cat.setdefault(m, p)
    return cat


def modelos_externos() -> list[str]:
    """Todos los ids de modelos externos del catálogo (todos los proveedores).
    La usa la API REST para etiquetar cada modelo con su tipo/proveedor."""
    ids: list[str] = []
    for p in proveedores_externos():
        ids.extend(p.modelos)
    return ids


def _es_externo(model: str | None) -> bool:
    return bool(model) and model in _catalogo_externo()


def _proveedor_para(modelo: str) -> Proveedor | None:
    """Proveedor externo que debe atender el modelo. Prioriza el proveedor que
    el frontend fijó por header (X-LLM-Provider); si no, lo infiere del catálogo
    por el id del modelo. Devuelve None para inferencia local (Ollama)."""
    ctx = get_llm_ctx()
    pid = ctx.get("proveedor", "")
    if pid == "local":
        return None
    if pid:
        prov = proveedor_por_id(pid)
        if prov is not None:
            return prov
    return _catalogo_externo().get(modelo)


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


def _sin_embeddings(nombres: list[str]) -> list[str]:
    """Descarta modelos de solo-embeddings (p.ej. nomic-embed-text): Ollama
    rechaza con 400 cualquier /api/chat contra ellos."""
    return [m for m in nombres if "embed" not in m.lower()]


# Modelo externo usado cuando el llamador no especifica ninguno y no hay
# ningún modelo LOCAL ya cargado en memoria de Ollama. openai/gpt-4o-mini es
# el más óptimo (calidad/costo/velocidad) para las tareas de este backend
# (resúmenes de medios, fundamentación normativa, conclusión).
MODELO_EXTERNO_DEFAULT = "openai/gpt-4o-mini"


def _resolver_modelo(model: str | None = None) -> str:
    """Determina qué modelo usar para chat.

    1. Si viene explícito (p.ej. `request.modelo` del frontend), se usa ese.
    2. Si hay un modelo LOCAL ya cargado en memoria de Ollama, se usa ese (así
       no se ignora un modelo que el usuario encendió a propósito).
    3. Si no, se usa el modelo externo por defecto (MODELO_EXTERNO_DEFAULT).

    Solo falla con ModeloNoCargadoError si ni siquiera el default externo
    está en el catálogo (config mal armada)."""
    if model:
        return model

    locales_cargados = _sin_embeddings(modelos_cargados_locales())
    if locales_cargados:
        return locales_cargados[0]

    if MODELO_EXTERNO_DEFAULT in _catalogo_externo():
        return MODELO_EXTERNO_DEFAULT

    raise ModeloNoCargadoError(
        "No hay ningún modelo de chat cargado en memoria. Selecciona un "
        "modelo y enciéndelo antes de continuar."
    )


def get_llm(model: str | None = None):
    modelo = _resolver_modelo(model)

    # Modelo externo: la inferencia corre en la nube del proveedor (no consume
    # el VPS). Todos los proveedores externos son compatibles con la API de
    # OpenAI, por eso usamos ChatOpenAI cambiando base_url + api_key.
    prov = _proveedor_para(modelo)
    if prov is not None:
        ctx = get_llm_ctx()
        # La key la manda el frontend (X-LLM-Api-Key); si no vino, se usa la de
        # entorno del proveedor como fallback opcional.
        key_frontend = ctx.get("api_key")
        api_key = key_frontend or prov.api_key_env
        logger.info(
            "[LLM] proveedor=%s | modelo=%s | key_origen=%s | key_sufijo=...%s",
            prov.id, modelo,
            "frontend" if key_frontend else "env (fallback)",
            api_key[-4:] if api_key else "(vacia)",
        )
        return ChatOpenAI(
            model=modelo,
            api_key=api_key,
            base_url=prov.base_url,
            temperature=0,
        )

    # Defensa en profundidad: aunque el frontend no debería dejar elegir local
    # si no está disponible, se valida también aquí antes de generar.
    apto, motivo = local_disponible()
    if not apto:
        raise InferenciaLocalNoDisponibleError(
            f"Inferencia local no disponible: {motivo}"
        )

    return ChatOllama(
        model=modelo,
        base_url=_resolver_ollama_base_url(),
        temperature=0,
        num_ctx=4096
    )


def log_uso_llm(log: logging.Logger, etiqueta: str, response) -> None:
    """Loguea los tokens y la velocidad de una respuesta del LLM, usando los
    conteos que devuelve el proveedor (tokenizer exacto del modelo).

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


def consultar_creditos_openrouter(api_key: str | None = None) -> dict | None:
    """Crédito restante REAL de la cuenta de OpenRouter (GET /credits): lo que
    queda para gastar, no una estimación. Devuelve None si falla (sin key,
    cuenta sin límite configurado que aplique, error de red, etc.)."""
    key = api_key or get_llm_ctx().get("api_key") or settings.openrouter_api_key
    if not key:
        logger.warning("[OPENROUTER] Sin API key para consultar /credits")
        return None

    base = settings.openrouter_base_url.rstrip("/")
    try:
        resp = httpx.get(
            f"{base}/credits",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}
        total = data.get("total_credits")
        usado = data.get("total_usage")
        restante = (total - usado) if total is not None and usado is not None else None
        return {"total_credits": total, "total_usage": usado, "restante_usd": restante}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OPENROUTER] No se pudo consultar /credits: %s", exc)
        return None


def precio_modelo_openrouter(modelo: str) -> dict | None:
    """Precio público del modelo en OpenRouter (USD por millón de tokens), vía
    GET /models (catálogo público, no requiere API key). Devuelve None si el
    modelo no aparece en el catálogo."""
    base = settings.openrouter_base_url.rstrip("/")
    try:
        resp = httpx.get(f"{base}/models", timeout=20.0)
        resp.raise_for_status()
        modelos = (resp.json() or {}).get("data") or []
        for m in modelos:
            if m.get("id") == modelo:
                pricing = m.get("pricing") or {}
                # OpenRouter devuelve el precio en USD POR TOKEN (no por millón).
                precio_prompt = float(pricing.get("prompt") or 0) * 1_000_000
                precio_completion = float(pricing.get("completion") or 0) * 1_000_000
                return {
                    "modelo": modelo,
                    "precio_input_por_millon_usd": precio_prompt,
                    "precio_output_por_millon_usd": precio_completion,
                }
        logger.warning("[OPENROUTER] Modelo '%s' no encontrado en /models", modelo)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OPENROUTER] No se pudo consultar /models: %s", exc)
        return None


def listar_modelos_locales() -> list[str]:
    """Solo los modelos que Ollama tiene descargados en el VPS (inferencia
    local). Si Ollama no responde, devuelve lista vacía."""
    ollama_url = _resolver_ollama_base_url().rstrip("/")
    endpoint = f"{ollama_url}/api/tags"
    try:
        response = httpx.get(endpoint, timeout=20.0)
        response.raise_for_status()
        payload = response.json()
        return [m.get("name") for m in payload.get("models", []) if m.get("name")]
    except Exception as exc:
        logger.warning("No se pudo listar modelos de Ollama: %s", exc)
        return []


def listar_modelos() -> list[str]:
    # Locales (Ollama) + externos (todos los proveedores del catálogo).
    return listar_modelos_locales() + modelos_externos()


# Tiempo que el modelo queda residente en memoria sin recibir peticiones antes
# de que Ollama lo descargue por su cuenta (no hay temporizador propio aquí).
KEEP_ALIVE_INACTIVIDAD = "5m"


def ollama_online() -> bool:
    """True si el servidor Ollama responde (para el estado en la pestaña Local)."""
    url = _resolver_ollama_base_url().rstrip("/")
    try:
        response = httpx.get(f"{url}/api/version", timeout=5.0)
        return response.status_code == 200
    except Exception:
        return False


def local_disponible() -> tuple[bool, str | None]:
    """Si la inferencia LOCAL de chat puede ofrecerse en este servidor.
    Requiere: hardware apto (GPU + RAM según config), Ollama en línea, y al
    menos un modelo de CHAT descargado (los de solo-embeddings no cuentan).
    Devuelve (disponible, motivo_si_no)."""
    apto, motivo = hardware_apto_para_local(
        min_ram_gb=settings.ollama_min_ram_gb,
        requiere_gpu=settings.ollama_requiere_gpu,
    )
    if not apto:
        return False, motivo

    if not ollama_online():
        return False, "El servidor Ollama no responde."

    if not _sin_embeddings(listar_modelos_locales()):
        return False, "No hay modelos de chat descargados en Ollama (solo embeddings, si acaso)."

    return True, None


def modelos_cargados_locales() -> list[str]:
    """Modelos de Ollama actualmente residentes en memoria (RAM/VRAM)."""
    url = _resolver_ollama_base_url().rstrip("/")
    try:
        response = httpx.get(f"{url}/api/ps", timeout=20.0)
        response.raise_for_status()
        return [m.get("name") for m in response.json().get("models", []) if m.get("name")]
    except Exception as exc:
        logger.warning("No se pudo consultar modelos cargados de Ollama: %s", exc)
        return []


def modelos_cargados() -> list[str]:
    """Modelos "listos" para el frontend: los de Ollama en memoria + los
    externos (que siempre están listos, viven en la nube)."""
    return modelos_cargados_locales() + modelos_externos()


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
    # OpenRouter no carga nada en RAM: la operación es un no-op exitoso.
    if _es_externo(model):
        return {"modelo": model, "ok": True, "en_memoria": True, "tiempo": 0.0}
    return _set_keep_alive(model, KEEP_ALIVE_INACTIVIDAD)


def descargar_modelo(model: str) -> dict:
    """Libera el modelo de memoria de inmediato (keep_alive=0)."""
    # OpenRouter no ocupa RAM del servidor: nada que liberar.
    if _es_externo(model):
        return {"modelo": model, "ok": True, "en_memoria": False, "tiempo": 0.0}
    return _set_keep_alive(model, 0)
