from fastapi import APIRouter, Depends

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm
from app.src.infrastructure.api_rest.schemas.investigacion import (
    ConciliacionRequest,
    ConciliacionResponse,
    ActualizarPropuestaRequest,
    ActualizarPropuestaResponse,
    ActualizarConciliacionRequest,
    ActualizarConciliacionResponse,
)
from app.src.application.services.investigacion.conciliacion_service import (
    generar_propuesta_conciliacion, actualizar_propuesta_conciliacion, actualizar_conciliacion,
)

router = APIRouter(
    prefix="/conciliacion",
    tags=["conciliacion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)


@router.post("/propuesta", response_model=ConciliacionResponse)
async def generar_propuesta(request: ConciliacionRequest) -> ConciliacionResponse:
    """
    Genera la propuesta de conciliación a partir de la CONCLUSIÓN del informe de
    atención (leída del store), no del texto completo del informe. Requiere que
    la investigación ya haya sido concluida (POST /investigacion/conclusion).
    """
    return await generar_propuesta_conciliacion(request)


@router.patch("/propuesta", response_model=ActualizarPropuestaResponse)
async def actualizar_propuesta(request: ActualizarPropuestaRequest) -> ActualizarPropuestaResponse:
    """Edita a mano el texto de la propuesta de conciliación, sin invocar al LLM."""
    return actualizar_propuesta_conciliacion(request)


@router.patch("/datos", response_model=ActualizarConciliacionResponse)
async def actualizar_datos_conciliacion(request: ActualizarConciliacionRequest) -> ActualizarConciliacionResponse:
    """
    Edita a mano los demás datos de la conciliación: postura del reclamante,
    puntos de acuerdo/desacuerdo y observaciones (no la propuesta de la
    empresa, que tiene su propio PATCH /conciliacion/propuesta). Sin invocar
    al LLM. Solo se pisan los campos que vengan en el request.
    """
    return actualizar_conciliacion(request)
