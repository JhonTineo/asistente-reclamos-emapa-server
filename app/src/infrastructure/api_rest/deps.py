"""Dependencias comunes para los endpoints REST."""

import logging

from fastapi import Request, HTTPException

from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter, emapa_token_ctx
from app.src.infrastructure.config.llm_context import set_llm_ctx
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.infrastructure.adapters.llm.model_catalog_adapter import ModelCatalogAdapter
from app.src.infrastructure.adapters.llm.openai_provider_adapter import OpenAiCompatProviderAdapter
from app.src.infrastructure.adapters.llm.ollama_provider_adapter import OllamaProviderAdapter
from app.src.infrastructure.config.settings import settings

logger = logging.getLogger("api.deps")

def get_llm_router() -> LlmRouterService:
    # Construir el mapa de modelos por proveedor desde los settings
    # Nota: Ollama no tiene un catálogo estático en settings; sus modelos
    # se descubren dinámicamente vía su API. Aquí se deja vacío y el
    # router aceptará cualquier modelo para el proveedor "ollama".
    provider_model_map = {
        "openrouter": [m.strip() for m in settings.openrouter_models.split(",") if m.strip()],
        "openai": [m.strip() for m in settings.openai_models.split(",") if m.strip()],
        "gemini": [m.strip() for m in settings.gemini_models.split(",") if m.strip()],
        "ollama": [],  # dinámico: se consultan vía Ollama API
    }
    
    catalogo = ModelCatalogAdapter(provider_model_map)
    
    providers = {
        "openrouter": OpenAiCompatProviderAdapter(settings.openrouter_base_url, settings.openrouter_api_key),
        "openai": OpenAiCompatProviderAdapter(settings.openai_base_url, settings.openai_api_key),
        "gemini": OpenAiCompatProviderAdapter(settings.gemini_base_url, settings.gemini_api_key),
        "ollama": OllamaProviderAdapter(settings.ollama_base_url, settings.ollama_requiere_gpu, settings.ollama_min_ram_gb),
    }
    
    return LlmRouterService(catalogo, providers)

async def usar_config_llm(request: Request) -> None:
    """Fija, para la petición en curso, el proveedor de LLM y su API key tomados
    de los headers ``X-LLM-Provider`` y ``X-LLM-Api-Key`` que envía el frontend.

    Si no vienen, ``get_llm`` infiere el proveedor por el id del modelo y usa la
    key de entorno como fallback (comportamiento previo intacto).

    Debe ser ``async def`` para correr en el mismo event-loop que el endpoint y
    que el ContextVar sea visible en toda la cadena de llamadas.
    """
    proveedor = request.headers.get("X-LLM-Provider")
    api_key = request.headers.get("X-LLM-Api-Key")
    set_llm_ctx(proveedor, api_key)
    logger.info(
        "[LLM] proveedor=%s | api_key=%s",
        proveedor or "(auto)",
        "sí" if api_key else "no (fallback env)",
    )


async def usar_token_emapa(request: Request) -> None:
    """Fija, para la petición en curso, el token de EMAPA tomado del header
    ``Authorization``. Si la petición no trae token, no se fija nada y las
    consultas a EMAPA usan el token de ``.env`` (settings.emapa_access_token).

    Acepta tanto ``Authorization: Bearer <token>`` como el token "pelado".

    IMPORTANTE: esta dependencia debe ser ``async def`` para que se ejecute
    en el mismo event-loop que el endpoint y los cambios al ContextVar
    sean visibles en toda la cadena de llamadas.
    """
    auth = request.headers.get("Authorization")
    logger.info("[AUTH] Header Authorization recibido: %s", f"{auth[:30]}…" if auth else None)
    if not auth or not auth.strip():
        logger.info("[AUTH] Petición sin token; se usará el token de .env")
        return

    auth = auth.strip()
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else auth
    logger.info("[AUTH] Token parseado (primeros 20 chars): %s…", token[:20])
    EmapaHttpAdapter().set_token(token)


async def requerir_token_emapa(request: Request) -> str:
    """Como ``usar_token_emapa`` pero OBLIGATORIO: si la petición no trae token
    responde 401. Se usa en la búsqueda del reclamo, que es el punto de entrada
    del flujo y con cuyo token se harán los pasos siguientes.

    Devuelve el token para que el endpoint lo guarde asociado al reclamo.
    """
    await usar_token_emapa(request)  # idempotente: fija el ContextVar si vino
    token = emapa_token_ctx.get()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Falta el token de EMAPA en el header Authorization.",
        )
    return token


async def asegurar_token_emapa(codreclamo: str) -> None:
    """Garantiza que haya token para las consultas a EMAPA de este reclamo.

    Si la petición trajo token (ContextVar ya fijado por ``usar_token_emapa``),
    se respeta. Si no, se recupera el token guardado al buscar el reclamo. Si
    tampoco existe, las consultas usarán el token de ``.env``.
    """
    if emapa_token_ctx.get():
        return
    token = informe_store.obtener_token(codreclamo)
    if token:
        EmapaHttpAdapter().set_token(token)
        logger.debug("[AUTH] Token recuperado del store para reclamo %s", codreclamo)
    else:
        logger.debug("[AUTH] Sin token guardado para reclamo %s; se usará .env", codreclamo)

