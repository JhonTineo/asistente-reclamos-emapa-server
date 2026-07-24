import asyncio

from fastapi import APIRouter, Depends, HTTPException
from app.src.infrastructure.api_rest.deps import usar_config_llm
from app.src.infrastructure.api_rest.schemas.modelo import (
    ModeloResponse,
    ModelosListResponse,
    ModelosCargadosResponse,
    ModeloAccionRequest,
    ModeloAccionResponse,
    ProveedorResponse,
    ProveedoresListResponse,
)
from starlette.concurrency import run_in_threadpool
from app.src.application.adapters.llm import (
    listar_modelos,
    listar_modelos_locales,
    modelos_cargados,
    modelos_cargados_locales,
    ollama_online,
    local_disponible,
    cargar_modelo,
    descargar_modelo,
    modelos_externos,
    consultar_creditos_openrouter,
    precio_modelo_openrouter,
)
from app.src.application.adapters.proveedores import proveedores_externos

router = APIRouter(prefix="/modelos", tags=["modelos"])


# Cuántos tokens se asume que consume UNA atención de reclamo completa
# (objetivos + medios + conclusión + propuesta + resolución). Cifra fija
# definida a mano (no medida); ajustar si el promedio real difiere mucho.
TOKENS_POR_RECLAMO_DEFAULT = 10_000


@router.get("/local/estado")
def estado_local() -> dict:
    """Estado del servidor Ollama local: si responde, qué modelos tiene
    descargados, cuáles están cargados en memoria, y si el hardware es apto
    para inferencia local de chat. Alimenta la pestaña Local."""
    disponible, motivo = local_disponible()
    return {
        "online": ollama_online(),
        "modelos": listar_modelos_locales(),
        "en_memoria": modelos_cargados_locales(),
        "disponible": disponible,
        "motivo_no_disponible": motivo,
    }


@router.get("/proveedores", response_model=ProveedoresListResponse)
def proveedores() -> ProveedoresListResponse:
    """Catálogo de proveedores de inferencia para el frontend. Los externos
    (OpenRouter, OpenAI, Gemini) van primero: son la opción por defecto porque
    el backend puede tener una key de fallback configurada y no dependen de
    hardware. El local (Ollama) va al final y trae `disponible`/`motivo` según
    hardware/estado, para que el frontend lo deshabilite si corresponde. No se
    expone ninguna API key: el frontend manda la suya por header al generar."""
    externos = [
        ProveedorResponse(
            id=p.id,
            label=p.label,
            tipo=p.tipo,
            requiere_key=True,
            modelos=p.modelos,
        )
        for p in proveedores_externos()
    ]
    local_ok, local_motivo = local_disponible()
    local = ProveedorResponse(
        id="local",
        label="Local (Ollama)",
        tipo="ollama",
        requiere_key=False,
        modelos=listar_modelos_locales(),
        disponible=local_ok,
        motivo_no_disponible=local_motivo,
    )
    return ProveedoresListResponse(
        proveedores=externos + [local],
        proveedor_default=externos[0].id if externos else "local",
    )


@router.get("", response_model=ModelosListResponse)
def listar() -> ModelosListResponse:
    """Modelos disponibles para el frontend. Incluye los locales de Ollama
    (descargados en el VPS) y los externos de OpenRouter (nube). Cada uno lleva
    su `tipo` para que el frontend los agrupe en 'inferencia local' vs
    'inferencia externa'. Si Ollama no responde, solo se listan los externos."""
    externos = set(modelos_externos())
    return ModelosListResponse(
        modelos=[
            ModeloResponse(id=m, tipo="externo" if m in externos else "local")
            for m in listar_modelos()
        ]
    )


@router.get("/cargados", response_model=ModelosCargadosResponse)
def cargados() -> ModelosCargadosResponse:
    """Modelos actualmente residentes en memoria (para pintar el estado del
    botón de encendido/apagado al cargar la página)."""
    return ModelosCargadosResponse(modelos=modelos_cargados())


@router.post("/cargar", response_model=ModeloAccionResponse)
def cargar(request: ModeloAccionRequest) -> ModeloAccionResponse:
    """Precarga el modelo en memoria sin generar tokens (botón "encender")."""
    resultado = cargar_modelo(request.modelo)
    return ModeloAccionResponse(**resultado)


@router.post("/descargar", response_model=ModeloAccionResponse)
def descargar(request: ModeloAccionRequest) -> ModeloAccionResponse:
    """Libera el modelo de memoria de inmediato (botón "apagar")."""
    resultado = descargar_modelo(request.modelo)
    return ModeloAccionResponse(**resultado)


@router.get("/creditos", dependencies=[Depends(usar_config_llm)])
async def creditos_disponibles(
    modelo: str = "openai/gpt-4o-mini",
    tokens_por_reclamo: int = TOKENS_POR_RECLAMO_DEFAULT,
) -> dict:
    """Cuántos reclamos se pueden atender con el crédito que queda en
    OpenRouter, consultando datos REALES de su API (no una muestra local):

    1. GET /credits -> dinero restante en la cuenta.
    2. GET /models  -> precio público del modelo seleccionado (USD/token).
    3. tokens_disponibles = dinero_restante / precio_promedio_por_token.
    4. reclamos_estimados = tokens_disponibles / tokens_por_reclamo.

    El precio promedio por token es el promedio simple de precio de entrada y
    salida del modelo (no depende de una proporción entrada/salida medida)."""
    creditos, precio = await asyncio.gather(
        run_in_threadpool(consultar_creditos_openrouter),
        run_in_threadpool(precio_modelo_openrouter, modelo),
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
        if dinero_restante is not None and precio_promedio_por_token > 0
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
