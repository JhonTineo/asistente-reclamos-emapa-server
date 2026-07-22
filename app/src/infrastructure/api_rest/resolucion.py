import time
import logging

from fastapi import APIRouter, HTTPException, Depends
from starlette.concurrency import run_in_threadpool

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm
from app.src.infrastructure.api_rest.schemas.investigacion import (
    ResolucionRequest,
    ResolucionResponse,
    ActualizarResolucionTextoRequest,
    ActualizarResolucionTextoResponse,
)
from app.src.application.usecase.agents.resolucion import ResolucionAgent
from app.src.application.services.informe.informe_store import informe_store

logger = logging.getLogger("api.resolucion")

router = APIRouter(
    prefix="/resolucion",
    tags=["resolucion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)


@router.post("", response_model=ResolucionResponse)
async def generar_resolucion(request: ResolucionRequest) -> ResolucionResponse:
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
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /resolucion] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                "Genere el informe de atención antes de la resolución."
            ),
        )
    if not informe.conclusion or not informe.veredicto:
        raise HTTPException(
            status_code=409,
            detail=(
                "El informe aún no tiene conclusión con veredicto. Genere el "
                "informe (paso de conclusión) antes de la resolución."
            ),
        )

    resolucion_agent = ResolucionAgent(model=request.modelo)
    resultado = await run_in_threadpool(
        resolucion_agent.generar_resolucion,
        informe, request.propuesta_conciliacion, request.propuesta_reclamante, request.observaciones,
    )
    # Se guarda en el informe (no solo se devuelve) para poder recuperarla si
    # el frontend recarga la página después de este paso.
    informe.resolucion = resultado["resolucion"]

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /resolucion] COMPLETADO | tipo=%s | tiempo=%.2fs", resultado["tipo"], tiempo)
    logger.info("=" * 60)

    return ResolucionResponse(
        codreclamo=request.codreclamo,
        tipo=resultado["tipo"],
        resolucion=resultado["resolucion"],
        tiempo=tiempo,
    )


@router.patch("", response_model=ActualizarResolucionTextoResponse)
async def actualizar_resolucion(request: ActualizarResolucionTextoRequest) -> ActualizarResolucionTextoResponse:
    """Edita a mano el texto de la resolución, sin invocar al LLM."""
    actualizado = informe_store.actualizar_resolucion(request.codreclamo, request.resolucion)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    return ActualizarResolucionTextoResponse(codreclamo=request.codreclamo, resolucion=request.resolucion)
