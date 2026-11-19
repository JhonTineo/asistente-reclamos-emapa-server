"""Tokens que consumió la última llamada al LLM hecha desde este hilo.

El adaptador del proveedor lo anota al recibir la respuesta y el constructor de
contexto lo lee al registrar la llamada. Va por hilo porque varias llamadas
corren a la vez (medios y fundamentación en paralelo), cada una en su hilo.
"""

import threading

_local = threading.local()


def anotar(entrada: int | None, cacheados: int | None, salida: int | None) -> None:
    _local.uso = {"entrada": entrada, "cacheados": cacheados, "salida": salida}


def limpiar() -> None:
    _local.uso = None


def ultimo() -> dict | None:
    return getattr(_local, "uso", None)


def desde_respuesta(response) -> None:
    """Lee el uso de un AIMessage de LangChain. ``usage_metadata`` es el formato
    normalizado; ``token_usage`` (formato OpenAI) es el respaldo para versiones
    o proveedores que no lo rellenan."""
    um = getattr(response, "usage_metadata", None) or {}
    if um:
        detalle = um.get("input_token_details") or {}
        anotar(um.get("input_tokens"), detalle.get("cache_read"), um.get("output_tokens"))
        return
    tu = (getattr(response, "response_metadata", None) or {}).get("token_usage") or {}
    if tu:
        detalle = tu.get("prompt_tokens_details") or {}
        anotar(tu.get("prompt_tokens"), detalle.get("cached_tokens"), tu.get("completion_tokens"))
