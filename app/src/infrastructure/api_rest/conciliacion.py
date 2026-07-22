import time
import logging

from fastapi import APIRouter, HTTPException, Depends
from starlette.concurrency import run_in_threadpool

from app.src.infrastructure.api_rest.deps import usar_token_emapa, usar_config_llm
from app.src.infrastructure.api_rest.schemas.investigacion import (
    ConciliacionRequest,
    ConciliacionResponse,
)
from app.src.application.usecase.agents.conciliador import ConciliadorAgent
from app.src.application.services.informe.informe_store import informe_store

logger = logging.getLogger("api.conciliacion")

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
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /conciliacion/propuesta] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                "Genere el informe de atención antes de la propuesta de conciliación."
            ),
        )
    if not informe.conclusion or not informe.veredicto:
        raise HTTPException(
            status_code=409,
            detail=(
                "El informe aún no tiene conclusión con veredicto. Genere el "
                "informe (paso de conclusión) antes de la propuesta."
            ),
        )

    conciliador = ConciliadorAgent(model=request.modelo)
    resultado = await run_in_threadpool(
        conciliador.generar_propuesta,
        request.codreclamo, informe.veredicto, informe.conclusion, informe.numero,
    )
    # Se guarda en el informe (no solo se devuelve) para poder recuperarla si
    # el frontend recarga la página antes de llegar a la resolución.
    informe.propuesta_conciliacion = resultado["propuesta"]

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /conciliacion/propuesta] COMPLETADO | veredicto=%s | tiempo=%.2fs",
                informe.veredicto, tiempo)
    logger.info("=" * 60)

    return ConciliacionResponse(
        codreclamo=request.codreclamo,
        propuesta=resultado["propuesta"],
        tiempo=tiempo,
    )
