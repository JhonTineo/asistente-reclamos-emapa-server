"""Descubrimiento EN VIVO de los modelos gratuitos de cada proveedor externo.

Por qué existe: tener los ids de modelo fijos en settings ya nos falló dos veces
(OpenCode servía `deepseek-v4-flash-free` y teníamos `opencode/deepseek-...`;
Cloudflare renombró su catálogo y los ids sin sufijo `-fp8` dejaron de existir).
Si un proveedor retira un modelo gratuito y ofrece otro, el backend debe
enterarse solo, sin que haya que tocar código ni redesplegar.

No hay una señal universal de "gratuito": cada proveedor la expone distinto
(pricing en OpenRouter, campo `tier` en Plugsky, sufijo `-free` en OpenCode,
capa entera gratuita en Groq/Gemini/Mistral...). Por eso hay UNA ESTRATEGIA POR
PROVEEDOR con firma común, registradas en ESTRATEGIAS.

Se consulta bajo demanda (cuando el frontend selecciona un proveedor), nunca
los N proveedores a la vez: así el selector hace una sola llamada HTTP en vez
de esperar al más lento de todos.
"""

import logging
from typing import Callable, NamedTuple

import httpx

logger = logging.getLogger("tools.llm.descubrimiento")

# Timeout corto: esto alimenta un selector de UI. Si un proveedor tarda más que
# esto, es preferible degradar a la lista estática que dejar la pantalla colgada.
TIMEOUT_DESCUBRIMIENTO = 12.0

# Familias que el proveedor lista pero que NO sirven para chat (transcripción,
# embeddings, moderación, voz, imagen). Se filtran por subcadena del id porque
# ningún proveedor expone un campo homogéneo para distinguirlas.
_NO_CHAT = (
    "whisper", "embed", "guard", "orpheus", "tts", "rerank", "moderation",
    "safeguard", "imagen", "veo", "image", "aqa", "bge-", "reranker",
)


class ModeloDescubierto(NamedTuple):
    id: str
    nombre: str
    gratuito: bool


def es_modelo_de_chat(modelo_id: str) -> bool:
    return not any(t in modelo_id.lower() for t in _NO_CHAT)


def _get(url: str, api_key: str, params: dict | None = None) -> dict:
    r = httpx.get(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        params=params,
        timeout=TIMEOUT_DESCUBRIMIENTO,
    )
    r.raise_for_status()
    return r.json()


def _listar(base_url: str, api_key: str) -> list[dict]:
    """GET /models estándar (OpenAI-compatible)."""
    res = _get(base_url.rstrip("/") + "/models", api_key)
    if isinstance(res, list):
        return res
    return res.get("data", [])


# --------------------------------------------------------------------------
# Estrategias por proveedor
# --------------------------------------------------------------------------

def _openrouter(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """OpenRouter sí publica precios: gratuito == prompt y completion a 0."""
    out = []
    for m in _listar(base_url, api_key):
        pr = m.get("pricing") or {}
        gratis = (
            str(pr.get("prompt", "1")) in ("0", "0.0")
            and str(pr.get("completion", "1")) in ("0", "0.0")
        )
        if gratis and es_modelo_de_chat(m["id"]):
            out.append(ModeloDescubierto(m["id"], m.get("name") or m["id"], True))
    return out


def _groq(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """Toda la capa de Groq es gratuita (limitada por rate), así que solo hay
    que quedarse con los modelos de texto activos."""
    out = []
    for m in _listar(base_url, api_key):
        if not m.get("active", True) or not es_modelo_de_chat(m["id"]):
            continue
        if "text" not in (m.get("output_modalities") or ["text"]):
            continue
        out.append(ModeloDescubierto(m["id"], m["id"], True))
    return out


def _mistral(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """Mistral no publica precio en /models, pero sí una capacidad explícita."""
    out = []
    for m in _listar(base_url, api_key):
        if (m.get("capabilities") or {}).get("completion_chat") and es_modelo_de_chat(m["id"]):
            out.append(ModeloDescubierto(m["id"], m.get("name") or m["id"], True))
    return out


def _plugsky(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """Plugsky es el único con un campo `tier` explícito."""
    return [
        ModeloDescubierto(m["id"], m.get("name") or m["id"], True)
        for m in _listar(base_url, api_key)
        if m.get("tier") == "free"
    ]


def _opencode(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """OpenCode Zen marca lo gratuito con el sufijo `-free` en el propio id."""
    return [
        ModeloDescubierto(m["id"], m["id"], True)
        for m in _listar(base_url, api_key)
        if m["id"].endswith("-free")
    ]


def _gemini(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """Gemini devuelve los ids con prefijo `models/`, que hay que quitar para
    poder usarlos como modelo en las peticiones de chat."""
    out = []
    for m in _listar(base_url, api_key):
        mid = m["id"].removeprefix("models/")
        if "gemini" in mid and es_modelo_de_chat(mid):
            out.append(ModeloDescubierto(mid, m.get("display_name") or mid, True))
    return out


def _cerebras(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    return [
        ModeloDescubierto(m["id"], m["id"], True)
        for m in _listar(base_url, api_key)
        if es_modelo_de_chat(m["id"])
    ]


def _githubmodels(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """GitHub Models (Azure AI) devuelve los ids como:
    'azureml://registries/azure-openai/models/gpt-4o-mini/versions/1'
    Pero para el chat requiere el nombre corto ('gpt-4o-mini')."""
    out = []
    for m in _listar(base_url, api_key):
        mid = m["id"]
        # Extraer el nombre corto del medio de la URI
        if "/models/" in mid:
            partes = mid.split("/models/")
            if len(partes) > 1:
                mid = partes[1].split("/")[0]
        
        if es_modelo_de_chat(mid):
            out.append(ModeloDescubierto(mid, m.get("name") or mid, True))
    return out


def _cloudflare(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """Cloudflare NO soporta GET /v1/models (devuelve 405). Su catálogo vive en
    /ai/models/search, a nivel de cuenta y con filtro por tarea."""
    cuenta_url = base_url.rstrip("/").removesuffix("/v1")
    d = _get(
        cuenta_url + "/models/search",
        api_key,
        params={"task": "Text Generation", "per_page": 100},
    )
    return [
        ModeloDescubierto(m["name"], m.get("name"), True)
        for m in d.get("result", [])
        if m.get("name") and es_modelo_de_chat(m["name"])
    ]


def _openai_compat_generico(base_url: str, api_key: str) -> list[ModeloDescubierto]:
    """Fallback para proveedores sin estrategia propia: se listan sus modelos de
    chat sin poder afirmar si son gratuitos (se marcan como no-gratuitos para no
    prometer algo que no se verificó)."""
    return [
        ModeloDescubierto(m["id"], m.get("name") or m["id"], False)
        for m in _listar(base_url, api_key)
        if es_modelo_de_chat(m["id"])
    ]


Estrategia = Callable[[str, str], list[ModeloDescubierto]]

ESTRATEGIAS: dict[str, Estrategia] = {
    "openrouter": _openrouter,
    "groq": _groq,
    "mistral": _mistral,
    "plugsky": _plugsky,
    "opencode": _opencode,
    "gemini": _gemini,
    "cerebras": _cerebras,
    "cloudflare": _cloudflare,
    "githubmodels": _githubmodels,
}


def descubrir_modelos_gratuitos(
    proveedor_id: str, base_url: str, api_key: str
) -> list[ModeloDescubierto]:
    """Modelos de chat gratuitos que el proveedor ofrece AHORA MISMO.

    Lanza la excepción original si la consulta falla: el llamador decide si
    degrada a la lista estática de settings. No se traga el error en silencio
    para que la causa (401, timeout, 405...) llegue al log."""
    fn = ESTRATEGIAS.get(proveedor_id, _openai_compat_generico)
    modelos = fn(base_url, api_key)
    logger.info(
        "[DESCUBRIMIENTO] %s -> %d modelo(s) de chat gratuitos", proveedor_id, len(modelos),
    )
    return modelos
