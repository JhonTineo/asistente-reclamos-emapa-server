from fastapi import APIRouter
from app.schemas.modelo import ModeloResponse, ModelosListResponse
from app.core.llm import listar_modelos
from app.core.config import settings

router = APIRouter(prefix="/modelos", tags=["modelos"])


@router.get("", response_model=ModelosListResponse)
def listar() -> ModelosListResponse:
    modelos = listar_modelos()

    if not modelos:
        modelos = [settings.ollama_generator_model]

    return ModelosListResponse(modelos=[ModeloResponse(id=m) for m in modelos])
