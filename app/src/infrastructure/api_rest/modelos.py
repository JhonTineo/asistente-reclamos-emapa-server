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

router = APIRouter(prefix="/modelos", tags=["modelos"])


@router.get("", response_model=ModelosListResponse)
def listar() -> ModelosListResponse:
    """Modelos que Ollama tiene descargados (no implica que estén cargados en
    memoria; para eso ver /modelos/cargados). Sin ningún nombre fijo de
    respaldo: si Ollama no responde, devuelve la lista vacía tal cual."""
    return ModelosListResponse(modelos=[ModeloResponse(id=m) for m in listar_modelos()])


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
