from fastapi import APIRouter
from app.src.infrastructure.api_rest.schemas.modelo import (
    ModeloResponse,
    ModelosListResponse,
    ModelosCargadosResponse,
    ModeloAccionRequest,
    ModeloAccionResponse,
    ProveedorResponse,
    ProveedoresListResponse,
)
from app.src.application.adapters.llm import (
    listar_modelos,
    listar_modelos_locales,
    modelos_cargados,
    modelos_cargados_locales,
    ollama_online,
    cargar_modelo,
    descargar_modelo,
    modelos_externos,
)
from app.src.application.adapters.proveedores import proveedores_externos

router = APIRouter(prefix="/modelos", tags=["modelos"])


@router.get("/local/estado")
def estado_local() -> dict:
    """Estado del servidor Ollama local: si responde, qué modelos tiene
    descargados y cuáles están cargados en memoria. Alimenta la pestaña Local."""
    return {
        "online": ollama_online(),
        "modelos": listar_modelos_locales(),
        "en_memoria": modelos_cargados_locales(),
    }


@router.get("/proveedores", response_model=ProveedoresListResponse)
def proveedores() -> ProveedoresListResponse:
    """Catálogo de proveedores de inferencia para el frontend: el local (Ollama,
    sin key) y los externos (OpenRouter, OpenAI, Gemini). No expone ninguna API
    key: el frontend ingresa la suya y la envía por header al generar."""
    locales = ProveedorResponse(
        id="local",
        label="Local (Ollama)",
        tipo="ollama",
        requiere_key=False,
        modelos=listar_modelos_locales(),
    )
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
    return ProveedoresListResponse(proveedores=[locales] + externos)


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
