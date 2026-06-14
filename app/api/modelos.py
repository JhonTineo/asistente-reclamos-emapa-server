from fastapi import APIRouter
from app.schemas.modelo import ModeloResponse, ModelosListResponse
from app.core.llm import listar_modelos

router = APIRouter(prefix="/modelos", tags=["modelos"])


@router.get("", response_model=ModelosListResponse)
def listar() -> ModelosListResponse:
    modelos = listar_modelos()
    return ModelosListResponse(modelos=[ModeloResponse(id=m) for m in modelos])
