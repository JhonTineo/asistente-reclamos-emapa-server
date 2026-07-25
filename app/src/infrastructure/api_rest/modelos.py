import asyncio
import logging
import time

import httpx

from fastapi import APIRouter, Depends, HTTPException
from app.src.infrastructure.api_rest.deps import (
    usar_config_llm,
    catalogo_externo,
    PROVEEDOR_PREDETERMINADO,
    MODELO_PREDETERMINADO,
)
from app.src.infrastructure.config.settings import settings
from app.src.infrastructure.config.llm_context import get_llm_ctx
from app.src.infrastructure.adapters.llm.ollama_provider_adapter import (
    modelos_chat_instalados,
    es_modelo_de_embeddings,
)
from app.src.infrastructure.adapters.llm.descubrimiento_modelos import (
    descubrir_modelos_gratuitos,
)
from app.src.infrastructure.api_rest.schemas.modelo import (
    ModeloResponse,
    ModelosListResponse,
    ModelosCargadosResponse,
    ModeloAccionRequest,
    ModeloAccionResponse,
    ModeloDisponibleResponse,
    ModelosProveedorResponse,
    ProveedorResponse,
    ProveedoresListResponse,
)

logger = logging.getLogger("api.modelos")

router = APIRouter(prefix="/modelos", tags=["modelos"])

TOKENS_POR_RECLAMO_DEFAULT = 10_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ollama_online() -> bool:
    """Comprueba si el servidor Ollama local responde."""
    try:
        r = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _listar_modelos_ollama() -> list[str]:
    """Modelos de CHAT descargados en Ollama (vacío si no responde).

    Excluye los de solo-embeddings: ofrecerlos en el selector del frontend
    garantiza un 400 de Ollama en cuanto el usuario elija uno."""
    return modelos_chat_instalados(settings.ollama_base_url)


def _modelos_cargados_ollama() -> list[str]:
    """Modelos de CHAT actualmente cargados en memoria de Ollama.

    Filtra los de embeddings por el mismo motivo que _listar_modelos_ollama:
    el de embeddings vive cargado para el RAG y no es un modelo elegible."""
    try:
        r = httpx.get(f"{settings.ollama_base_url}/api/ps", timeout=3)
        if r.status_code == 200:
            nombres = [m["name"] for m in r.json().get("models", [])]
            return [n for n in nombres if not es_modelo_de_embeddings(n)]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/local/estado")
def estado_local() -> dict:
    """Estado del servidor Ollama local: si responde, qué modelos tiene
    descargados, cuáles están cargados en memoria."""
    online = _ollama_online()
    return {
        "online": online,
        "modelos": _listar_modelos_ollama() if online else [],
        "en_memoria": _modelos_cargados_ollama() if online else [],
        "disponible": online,
        "motivo_no_disponible": None if online else "Ollama no responde",
    }


@router.get("/proveedores", response_model=ProveedoresListResponse)
def proveedores() -> ProveedoresListResponse:
    """Catálogo de proveedores de inferencia para el frontend.

    Es ESTÁTICO a propósito: no consulta ninguna API externa, así que responde
    al instante. Los modelos de cada proveedor se piden aparte, y solo del que
    el usuario seleccione, con GET /modelos/proveedor/{id}."""
    externos = [
        ProveedorResponse(
            id=p.id, label=p.label, tipo="openai_compat",
            requiere_key=True, modelos=p.modelos,
        )
        for p in catalogo_externo().values()
    ]

    ollama_ok = _ollama_online()
    local = ProveedorResponse(
        id="local", label="Local (Ollama)", tipo="ollama",
        requiere_key=False,
        modelos=_listar_modelos_ollama() if ollama_ok else [],
        disponible=ollama_ok,
        motivo_no_disponible=None if ollama_ok else "Ollama no responde",
    )

    return ProveedoresListResponse(
        proveedores=externos + [local],
        proveedor_default=PROVEEDOR_PREDETERMINADO,
    )


@router.get("/proveedor/{proveedor_id}", response_model=ModelosProveedorResponse)
def modelos_de_proveedor(proveedor_id: str) -> ModelosProveedorResponse:
    """Modelos de chat que ese proveedor ofrece AHORA MISMO, consultados en vivo.

    Se llama cuando el usuario selecciona un proveedor en el frontend, para que
    el selector de modelos nunca ofrezca ids que el proveedor ya retiró (nos pasó
    con OpenCode y Cloudflare). Si la consulta falla, se devuelve la lista
    estática de settings con `descubierto=false` en vez de dejar el selector
    vacío."""
    pid = proveedor_id.strip().lower()

    if pid in ("local", "ollama"):
        return ModelosProveedorResponse(
            proveedor="local",
            modelos=[
                ModeloDisponibleResponse(id=m, nombre=m, gratuito=True)
                for m in _listar_modelos_ollama()
            ],
        )

    p = catalogo_externo().get(pid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Proveedor desconocido: {proveedor_id}")

    if not p.api_key or not p.base_url:
        return ModelosProveedorResponse(
            proveedor=pid, modelos=[], descubierto=False,
            error="Proveedor sin API key o base_url configurada.",
        )

    try:
        modelos = [
            ModeloDisponibleResponse(id=m.id, nombre=m.nombre, gratuito=m.gratuito)
            for m in descubrir_modelos_gratuitos(pid, p.base_url, p.api_key)
        ]
        descubierto, error = True, None
    except Exception as e:  # noqa: BLE001
        logger.warning("[MODELOS] Descubrimiento falló para '%s': %s", pid, e)
        modelos = [
            ModeloDisponibleResponse(id=m, nombre=m, gratuito=False) for m in p.modelos
        ]
        descubierto, error = False, f"{type(e).__name__}: {e}"

    # El predeterminado es de PAGO, así que el descubrimiento de gratuitos nunca
    # lo devuelve: se inyecta a mano y se pone primero para que el frontend lo
    # preseleccione.
    if pid == PROVEEDOR_PREDETERMINADO:
        modelos = [m for m in modelos if m.id != MODELO_PREDETERMINADO]
        modelos.insert(0, ModeloDisponibleResponse(
            id=MODELO_PREDETERMINADO, nombre=MODELO_PREDETERMINADO,
            gratuito=False, predeterminado=True,
        ))

    return ModelosProveedorResponse(
        proveedor=pid, modelos=modelos, descubierto=descubierto, error=error,
    )


@router.get("", response_model=ModelosListResponse)
def listar() -> ModelosListResponse:
    """Modelos disponibles para el frontend (externos + locales)."""
    externos = [m for p in catalogo_externo().values() for m in p.modelos]
    locales = _listar_modelos_ollama()

    modelos = (
        [ModeloResponse(id=m, tipo="externo") for m in externos]
        + [ModeloResponse(id=m, tipo="local") for m in locales]
    )
    return ModelosListResponse(modelos=modelos)


@router.get("/cargados", response_model=ModelosCargadosResponse)
def cargados() -> ModelosCargadosResponse:
    """Modelos actualmente residentes en memoria de Ollama."""
    return ModelosCargadosResponse(modelos=_modelos_cargados_ollama())


@router.post("/cargar", response_model=ModeloAccionResponse)
def cargar(request: ModeloAccionRequest) -> ModeloAccionResponse:
    """Precarga el modelo en memoria de Ollama sin generar tokens."""
    t_inicio = time.perf_counter()
    try:
        r = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": request.modelo, "keep_alive": "10m"},
            timeout=120,
        )
        ok = r.status_code == 200
        return ModeloAccionResponse(
            modelo=request.modelo,
            ok=ok,
            en_memoria=ok,
            tiempo=time.perf_counter() - t_inicio,
            error=None if ok else r.text,
        )
    except Exception as e:
        return ModeloAccionResponse(
            modelo=request.modelo, ok=False, en_memoria=False,
            tiempo=time.perf_counter() - t_inicio, error=str(e),
        )


@router.post("/descargar", response_model=ModeloAccionResponse)
def descargar(request: ModeloAccionRequest) -> ModeloAccionResponse:
    """Libera el modelo de memoria de Ollama."""
    t_inicio = time.perf_counter()
    try:
        r = httpx.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": request.modelo, "keep_alive": "0"},
            timeout=30,
        )
        ok = r.status_code == 200
        return ModeloAccionResponse(
            modelo=request.modelo,
            ok=ok,
            # Descarga exitosa => el modelo ya NO está residente en memoria.
            en_memoria=not ok,
            tiempo=time.perf_counter() - t_inicio,
            error=None if ok else r.text,
        )
    except Exception as e:
        return ModeloAccionResponse(
            modelo=request.modelo, ok=False, en_memoria=True,
            tiempo=time.perf_counter() - t_inicio, error=str(e),
        )


@router.get("/creditos", dependencies=[Depends(usar_config_llm)])
async def creditos_disponibles(
    modelo: str = "openai/gpt-4o-mini",
    tokens_por_reclamo: int = TOKENS_POR_RECLAMO_DEFAULT,
) -> dict:
    """Créditos restantes en OpenRouter para estimar reclamos atendibles."""
    from starlette.concurrency import run_in_threadpool

    ctx = get_llm_ctx()
    api_key = ctx.get("api_key") or settings.openrouter_api_key
    if not api_key:
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar el crédito de OpenRouter (falta API key).",
        )

    def _consultar_creditos():
        try:
            r = httpx.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                total = data.get("total_credits", 0)
                usage = data.get("total_usage", 0)
                return {"total_credits": total, "total_usage": usage, "restante_usd": total - usage}
        except Exception:
            pass
        return None

    def _precio_modelo(model_id: str):
        try:
            r = httpx.get("https://openrouter.ai/api/v1/models", timeout=10)
            if r.status_code == 200:
                for m in r.json().get("data", []):
                    if m.get("id") == model_id:
                        pricing = m.get("pricing", {})
                        return {
                            "precio_input_por_millon_usd": float(pricing.get("prompt", 0)) * 1_000_000,
                            "precio_output_por_millon_usd": float(pricing.get("completion", 0)) * 1_000_000,
                        }
        except Exception:
            pass
        return None

    creditos, precio = await asyncio.gather(
        run_in_threadpool(_consultar_creditos),
        run_in_threadpool(_precio_modelo, modelo),
    )

    if creditos is None:
        raise HTTPException(
            status_code=502,
            detail="No se pudo consultar el crédito de OpenRouter (falta API key o falló la conexión).",
        )
    if precio is None:
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró el modelo '{modelo}' en el catálogo de OpenRouter.",
        )

    dinero_restante = creditos["restante_usd"]
    precio_prompt = precio["precio_input_por_millon_usd"]
    precio_completion = precio["precio_output_por_millon_usd"]
    precio_promedio_por_millon = (precio_prompt + precio_completion) / 2
    precio_promedio_por_token = precio_promedio_por_millon / 1_000_000

    tokens_disponibles = (
        dinero_restante / precio_promedio_por_token
        if precio_promedio_por_token > 0
        else None
    )
    reclamos_estimados = (
        int(tokens_disponibles / tokens_por_reclamo)
        if tokens_disponibles is not None and tokens_por_reclamo > 0
        else None
    )

    return {
        "modelo": modelo,
        "dinero_restante_usd": dinero_restante,
        "total_credits_usd": creditos["total_credits"],
        "total_usage_usd": creditos["total_usage"],
        "precio_input_por_millon_usd": precio_prompt,
        "precio_output_por_millon_usd": precio_completion,
        "precio_promedio_por_millon_usd": precio_promedio_por_millon,
        "tokens_disponibles": int(tokens_disponibles) if tokens_disponibles is not None else None,
        "tokens_por_reclamo": tokens_por_reclamo,
        "reclamos_estimados": reclamos_estimados,
    }
