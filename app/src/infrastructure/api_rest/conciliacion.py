import logging
from fastapi import APIRouter, Depends

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm, get_llm_router
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.infrastructure.api_rest.schemas.investigacion import (
    ConciliacionRequest,
    ConciliacionResponse,
    ActualizarPropuestaRequest,
    ActualizarPropuestaResponse,
    ActualizarConciliacionRequest,
    ActualizarConciliacionResponse,
    GuardarConciliacionRequest,
)
from app.src.application.services.investigacion.conciliacion_service import (
    generar_propuesta_conciliacion, actualizar_propuesta_conciliacion, actualizar_conciliacion, guardar_conciliacion
)

logger = logging.getLogger("api.conciliacion")

router = APIRouter(
    prefix="/conciliacion",
    tags=["conciliacion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)


@router.get("/propuesta", response_model=ConciliacionResponse)
async def generar_propuesta(codreclamo: str, modelo: str | None = None, llm_router: LlmRouterService = Depends(get_llm_router)) -> ConciliacionResponse:
    """
    Genera la propuesta de conciliación a partir de la CONCLUSIÓN del informe de
    atención, la propuesta de la empresa y la postura del reclamante. Guarda el
    resultado en el informe del store.
    """
    from app.src.infrastructure.api_rest.schemas.investigacion import ConciliacionRequest
    req = ConciliacionRequest(codreclamo=codreclamo, modelo=modelo)
    return await generar_propuesta_conciliacion(req, llm_router)


@router.post("/propuesta", response_model=ActualizarConciliacionResponse)
async def guardar_datos_conciliacion(request: GuardarConciliacionRequest) -> ActualizarConciliacionResponse:
    """
    Guarda todos los datos de la conciliación: propuesta de la empresa, postura
    del reclamante, puntos de acuerdo/desacuerdo y observaciones.
    """
    return guardar_conciliacion(request)


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
