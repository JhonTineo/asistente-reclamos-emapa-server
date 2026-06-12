from fastapi import APIRouter
from app.schemas.reclamo import ClasificarReclamoRequest, ClasificarReclamoResponse
from app.agent.clasificador import clasificar_reclamo

router = APIRouter(prefix="/reclamos", tags=["reclamos"])


@router.post("/clasificar", response_model=ClasificarReclamoResponse)
def clasificar(request: ClasificarReclamoRequest) -> ClasificarReclamoResponse:
    return clasificar_reclamo(
        reclamo_id=request.reclamo_id,
        detalle=request.detalle,
    )
