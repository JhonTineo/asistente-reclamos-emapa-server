"""Dependencias comunes para los endpoints REST."""

import logging
from typing import NamedTuple

from fastapi import Request, HTTPException

from app.src.infrastructure.adapters.emapa_http_adapter import EmapaHttpAdapter, emapa_token_ctx
from app.src.infrastructure.config.llm_context import set_llm_ctx
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.infrastructure.adapters.llm.model_catalog_adapter import ModelCatalogAdapter
from app.src.infrastructure.adapters.llm.openai_provider_adapter import OpenAiCompatProviderAdapter
from app.src.infrastructure.adapters.llm.ollama_provider_adapter import (
    OllamaProviderAdapter,
    modelos_chat_instalados,
)
from app.src.infrastructure.config.settings import settings

logger = logging.getLogger("api.deps")

# COMBO EXTERNO: los cinco proveedores de nube, EN ORDEN DE PRIORIDAD. Se
# intenta el primero y, si falla, se sigue con el resto (el "proxy"). Cambiar
# el orden de esta lista cambia la prioridad; es el único sitio que hay que
# tocar para ello.
#
# Orden fijado por pruebas reales (2026-07-25) sobre el flujo completo de
# /investigacion/objetivos, no solo "responde OK":
#   1. openrouter (gpt-4o-mini)      — rápido y completo, validado en producción.
#   2. groq (llama-3.3-70b-versatile)— rápido y completo.
#   3. cloudflare (70b-fp8-fast)     — rápido y completo.
#   4. gemini                         — rápido y completo.
#   5. mistral                        — rápido y completo.
#   6. opencode                      — funciona pero notablemente más lento.
#   7. cerebras                      — 402 payment_required en la cuenta actual;
#      último en la fila para que el resto no espere su fallo antes de intentar.
# El modelo cloudflare 8B (llama-3.1-8b-instruct-fp8) mostró truncar el JSON de
# forma INTERMITENTE con el prompt largo de objetivos (a veces completo, a veces
# cortado a mitad de frase con finish_reason mal reportado como "stop"); se dejó
# en segundo lugar en CLOUDFLARE_MODELS por si el 70b también llega a fallar.
PROVEEDORES_EXTERNOS = ["openrouter", "groq", "cloudflare", "mistral", "opencode", "plugsky", "githubmodels", "gemini", "deepseek", "siliconflow", "cerebras"]

# Lo que el frontend debe preseleccionar. OJO: gpt-4o-mini NO es gratuito
# (~0.15 USD / millón de tokens de entrada), pero es el de mejor relación
# calidad/costo/velocidad para las tareas de este backend, así que se ofrece
# siempre aunque el resto del selector sean modelos de capa gratuita. El
# endpoint /modelos/proveedor/{id} lo inyecta aunque el descubrimiento de
# gratuitos no lo devuelva, precisamente porque es de pago.
PROVEEDOR_PREDETERMINADO = "openrouter"
MODELO_PREDETERMINADO = "openai/gpt-4o-mini"

# Proveedor de inferencia LOCAL. Es un modo aparte: al elegirlo no hay proxy
# posible, solo cambian los modelos disponibles dentro del propio Ollama.
PROVEEDOR_LOCAL = "ollama"

# Alias que puede mandar el frontend en X-LLM-Provider para pedir modo local.
_ALIAS_LOCAL = {"local", "ollama"}


class ProveedorExterno(NamedTuple):
    id: str
    label: str
    base_url: str
    api_key: str
    modelos: list[str]


def catalogo_externo() -> dict[str, ProveedorExterno]:
    """FUENTE ÚNICA de los proveedores externos: la usan tanto el router (para
    enrutar) como /modelos y /modelos/proveedores (para poblar el selector del
    frontend). Antes cada uno tenía su propia lista y se desincronizaban."""
    return {
        p.id: p
        for p in (
            ProveedorExterno("openrouter", "OpenRouter",
                             settings.openrouter_base_url, settings.openrouter_api_key,
                             _csv(settings.openrouter_models)),
            
            ProveedorExterno("groq", "Groq",
                             settings.groq_base_url, settings.groq_api_key,
                             _csv(settings.groq_models)),
            
            ProveedorExterno("cloudflare", "Cloudflare Workers AI",
                             _cloudflare_base_url(), settings.cloudflare_api_key,
                             _csv(settings.cloudflare_models)),

            ProveedorExterno("gemini", "Gemini",
                             settings.gemini_base_url, settings.gemini_api_key,
                             _csv(settings.gemini_models)),

            ProveedorExterno("mistral", "Mistral",
                             settings.mistral_base_url, settings.mistral_api_key,
                             _csv(settings.mistral_models)),

            ProveedorExterno("plugsky", "Plugsky",
                             settings.plugsky_base_url, settings.plugsky_api_key,
                             _csv(settings.plugsky_models)),

            ProveedorExterno("githubmodels", "GitHub Models",
                             settings.githubmodels_base_url, settings.githubmodels_api_key,
                             _csv(settings.githubmodels_models)),

            ProveedorExterno("opencode", "OpenCode Zen",
                             settings.opencode_base_url, settings.opencode_api_key,
                             _csv(settings.opencode_models)),
            

           
            ProveedorExterno("siliconflow", "SiliconFlow",
                             settings.siliconflow_base_url, settings.siliconflow_api_key,
                             _csv(settings.siliconflow_models)),

             ProveedorExterno("deepseek", "DeepSeek",
                             settings.deepseek_base_url, settings.deepseek_api_key,
                             _csv(settings.deepseek_models)),

            ProveedorExterno("cerebras", "Cerebras",
                             settings.cerebras_base_url, settings.cerebras_api_key,
                             _csv(settings.cerebras_models)),
        )
    }


def _csv(valor: str) -> list[str]:
    """Lista de modelos desde el CSV de settings, sin vacíos."""
    return [m.strip() for m in valor.split(",") if m.strip()]


def _cloudflare_base_url() -> str:
    """Endpoint OpenAI-compatible de Workers AI. A diferencia del resto, la URL
    incorpora el id de cuenta, así que se arma en runtime. Si no está
    configurado se devuelve cadena vacía: el proveedor quedará inservible y el
    combo pasará al siguiente, en vez de mandar peticiones a una URL rota."""
    account = settings.cloudflare_account_id.strip()
    if not account:
        return ""
    return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"


def _resolver_orden_proveedores(proveedor: str | None) -> list[str]:
    """Traduce la elección del usuario (header X-LLM-Provider) al orden de
    proveedores que se intentarán.

    - modo LOCAL  -> solo Ollama, sin fallback: si falla, falla.
    - modo EXTERNO con proveedor concreto -> ese primero, luego el resto de
      externos (el "proxy" que da resiliencia si uno cae).
    - sin elección -> todos los externos. Nunca se cae a local por accidente.
    """
    pid = (proveedor or "").strip().lower()
    if pid in _ALIAS_LOCAL:
        return [PROVEEDOR_LOCAL]
    if pid in PROVEEDORES_EXTERNOS:
        return [pid] + [p for p in PROVEEDORES_EXTERNOS if p != pid]
    return list(PROVEEDORES_EXTERNOS)


def get_llm_router(request: Request) -> LlmRouterService:
    """Arma el router para ESTA petición, ya acotado al modo que eligió el
    usuario. La decisión vive acá (infraestructura, que es quien conoce los
    headers) y no dentro del router, que solo ejecuta la lista que recibe."""
    proveedor = request.headers.get("X-LLM-Provider")
    orden = _resolver_orden_proveedores(proveedor)
    es_local = orden == [PROVEEDOR_LOCAL]

    externos = catalogo_externo()
    provider_model_map = {
        **{pid: p.modelos for pid, p in externos.items()},
        # Los modelos de Ollama no están en settings: el usuario los descarga
        # cuando quiere. Se consultan en vivo, pero SOLO en modo local, para no
        # cobrarle una llamada HTTP (y su timeout si Ollama está caído) a cada
        # petición que en realidad va a un proveedor externo.
        PROVEEDOR_LOCAL: modelos_chat_instalados(settings.ollama_base_url) if es_local else [],
    }

    catalogo = ModelCatalogAdapter(provider_model_map)

    providers = {
        **{
            pid: OpenAiCompatProviderAdapter(p.base_url, p.api_key)
            for pid, p in externos.items()
        },
        PROVEEDOR_LOCAL: OllamaProviderAdapter(
            settings.ollama_base_url, settings.ollama_requiere_gpu, settings.ollama_min_ram_gb,
        ),
    }

    logger.info(
        "[LLM] modo=%s | pedido=%s | orden=%s",
        "local" if es_local else "externo", proveedor or "(auto)", orden,
    )
    return LlmRouterService(catalogo, providers, orden_proveedores=orden)

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

