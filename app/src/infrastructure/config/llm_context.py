from contextvars import ContextVar
from typing import Optional

# Almacena un dict con la config sobreescrita por petición HTTP
# Ej: {"proveedor": "openrouter", "api_key": "sk-..."}
llm_ctx: ContextVar[dict[str, Optional[str]]] = ContextVar("llm_ctx", default={})

def set_llm_ctx(proveedor: Optional[str], api_key: Optional[str]) -> None:
    llm_ctx.set({
        "proveedor": proveedor,
        "api_key": api_key,
    })

def get_llm_ctx() -> dict[str, Optional[str]]:
    return llm_ctx.get()
