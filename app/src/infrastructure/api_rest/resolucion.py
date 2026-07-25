import logging
from fastapi import APIRouter, Depends

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm, get_llm_router
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.infrastructure.api_rest.schemas.investigacion import (
    ResolucionRequest,
    ResolucionResponse,
    ActualizarResolucionTextoRequest,
    ActualizarResolucionTextoResponse,
)
from app.src.application.services.investigacion.resolucion_service import (
    generar_resolucion_final, actualizar_resolucion_texto,
)

logger = logging.getLogger("api.resolucion")

router = APIRouter(
    prefix="/resolucion",
    tags=["resolucion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)


@router.post("", response_model=ResolucionResponse)
async def generar_resolucion(request: ResolucionRequest, llm_router: LlmRouterService = Depends(get_llm_router)) -> ResolucionResponse:
    """
    Genera la resolución final del reclamo. El tipo (FUNDADO/INFUNDADO) NO lo
    decide el LLM: se toma del veredicto ya fijado en el informe (paso de
    conclusión); el LLM solo redacta los considerandos que lo fundamentan,
    usando los datos del reclamo y la conclusión de la investigación (ambos
    leídos del informe en el store) más la propuesta de conciliación de la
    empresa y la postura del cliente. Requiere que la investigación ya haya
    sido concluida (POST /investigacion/conclusion) y, normalmente, que ya
    exista una propuesta de conciliación (POST /conciliacion/propuesta).
    """
    return await generar_resolucion_final(request, llm_router)


@router.patch("", response_model=ActualizarResolucionTextoResponse)
async def actualizar_resolucion(request: ActualizarResolucionTextoRequest) -> ActualizarResolucionTextoResponse:
    """Edita a mano el texto de la resolución, sin invocar al LLM."""
    return actualizar_resolucion_texto(request)
