from fastapi import APIRouter
from app.src.infrastructure.api_rest.schemas.modelo import (
    ModeloResponse,
    ModelosListResponse,
    ModelosCargadosResponse,
    ModeloAccionRequest,
    ModeloAccionResponse,
)
from app.src.application.adapters.llm import (
    listar_modelos,
    modelos_cargados,
    cargar_modelo,
    descargar_modelo,
)
from app.src.application.adapters.config import settings

router = APIRouter(prefix="/modelos", tags=["modelos"])


@router.get("", response_model=ModelosListResponse)
def listar() -> ModelosListResponse:
    modelos = listar_modelos()

    if not modelos:
        modelos = [settings.ollama_generator_model]

    return ModelosListResponse(modelos=[ModeloResponse(id=m) for m in modelos])


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
