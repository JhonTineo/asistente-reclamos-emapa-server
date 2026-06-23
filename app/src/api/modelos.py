from fastapi import APIRouter
from app.src.schemas.modelo import ModeloResponse, ModelosListResponse
from app.src.core.llm import listar_modelos
from app.src.core.config import settings

router = APIRouter(prefix="/modelos", tags=["modelos"])


@router.get("", response_model=ModelosListResponse)
def listar() -> ModelosListResponse:
    modelos = listar_modelos()

    if not modelos:
        modelos = [settings.ollama_generator_model]

    return ModelosListResponse(modelos=[ModeloResponse(id=m) for m in modelos])
