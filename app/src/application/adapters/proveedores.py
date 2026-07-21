"""Registro de proveedores de LLM y config por peticion.

Casi todos los proveedores externos (OpenRouter, OpenAI, Gemini) son
compatibles con la API de OpenAI, asi que se manejan con un mismo cliente
(ChatOpenAI) cambiando base_url + api_key. Solo Ollama es aparte (local).

La API key efectiva se resuelve por peticion: si el frontend la manda por el
header X-LLM-Api-Key (ver deps.usar_config_llm), se usa esa; si no, cae al
valor de entorno (*_api_key en settings) como fallback opcional.
"""

from contextvars import ContextVar
from dataclasses import dataclass

from app.src.application.adapters.config import settings


@dataclass(frozen=True)
class Proveedor:
    id: str          # "openrouter" | "openai" | "gemini"
    label: str       # nombre visible en el frontend
    tipo: str        # "openai_compat" (todos los externos por ahora)
    base_url: str
    api_key_env: str  # key configurada en el backend (fallback opcional)
    modelos: list[str]


def _split(csv: str) -> list[str]:
    return [m.strip() for m in csv.split(",") if m.strip()]


def proveedores_externos() -> list[Proveedor]:
    """Catalogo de proveedores externos definidos en settings. El catalogo se
    expone SIN requerir key (la key solo hace falta al generar)."""
    return [
        Proveedor(
            "openrouter", "OpenRouter", "openai_compat",
            settings.openrouter_base_url, settings.openrouter_api_key,
            _split(settings.openrouter_models),
        ),
        Proveedor(
            "openai", "OpenAI", "openai_compat",
            settings.openai_base_url, settings.openai_api_key,
            _split(settings.openai_models),
        ),
        Proveedor(
            "gemini", "Gemini", "openai_compat",
            settings.gemini_base_url, settings.gemini_api_key,
            _split(settings.gemini_models),
        ),
    ]


def proveedor_por_id(pid: str) -> Proveedor | None:
    for p in proveedores_externos():
        if p.id == pid:
            return p
    return None


# ------------------------------------------------------------------ #
# Config LLM de la peticion en curso (la envia el frontend por headers).
# Mismo patron que el token de EMAPA (emapa_token_ctx).
# ------------------------------------------------------------------ #
llm_ctx: ContextVar[dict] = ContextVar("llm_ctx", default={})


def set_llm_ctx(proveedor: str | None, api_key: str | None) -> None:
    llm_ctx.set({
        "proveedor": (proveedor or "").strip(),
        "api_key": (api_key or "").strip(),
    })


def get_llm_ctx() -> dict:
    return llm_ctx.get()
