"""Servicio de aplicación para la conciliación: genera y actualiza la
propuesta de conciliación a partir de la conclusión ya fijada en el informe."""

import time
import logging

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.src.infrastructure.api_rest.schemas.investigacion import (
    ConciliacionRequest, ConciliacionResponse,
    ActualizarPropuestaRequest, ActualizarPropuestaResponse,
    ActualizarConciliacionRequest, ActualizarConciliacionResponse,
)
from app.src.application.usecase.agents.conciliador import ConciliadorAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.core.model.conciliacion import Conciliacion

logger = logging.getLogger("services.conciliacion_service")


async def generar_propuesta_conciliacion(request: ConciliacionRequest, llm_router: LlmRouterService) -> ConciliacionResponse:
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

    conciliador = ConciliadorAgent(llm_router=llm_router, model=request.modelo)
    resultado = await run_in_threadpool(
        conciliador.generar_propuesta,
        request.codreclamo, informe.veredicto, informe.conclusion, informe.numero,
    )
    # Se guarda en el informe (no solo se devuelve) para poder recuperarla si
    # el frontend recarga la página antes de llegar a la resolución. Los demás
    # campos (propuesta_reclamante, puntos_acuerdo, puntos_desacuerdo,
    # observaciones) se llenan aparte (edición manual / paso posterior).
    if informe.propuesta_conciliacion is None:
        informe.propuesta_conciliacion = Conciliacion()
    informe.propuesta_conciliacion.propuesta_empresa = resultado["propuesta"]

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /conciliacion/propuesta] COMPLETADO | veredicto=%s | tiempo=%.2fs",
                informe.veredicto, tiempo)
    logger.info("=" * 60)

    return ConciliacionResponse(
        codreclamo=request.codreclamo,
        propuesta=resultado["propuesta"],
        tiempo=tiempo,
    )


def actualizar_propuesta_conciliacion(request: ActualizarPropuestaRequest) -> ActualizarPropuestaResponse:
    """Edita a mano el texto de la propuesta de conciliación, sin invocar al LLM."""
    actualizado = informe_store.actualizar_propuesta(request.codreclamo, request.propuesta)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    return ActualizarPropuestaResponse(codreclamo=request.codreclamo, propuesta=request.propuesta)


def actualizar_conciliacion(request: ActualizarConciliacionRequest) -> ActualizarConciliacionResponse:
    """Edita a mano los demás datos de la conciliación (postura del
    reclamante, puntos de acuerdo/desacuerdo, observaciones), sin invocar al
    LLM. Solo pisa los campos que vengan en el request; el resto conserva su
    valor actual (el default de ``Conciliacion``, o lo editado antes)."""
    conciliacion = informe_store.actualizar_conciliacion(
        request.codreclamo,
        propuesta_reclamante=request.propuesta_reclamante,
        puntos_acuerdo=request.puntos_acuerdo,
        puntos_desacuerdo=request.puntos_desacuerdo,
        observaciones=request.observaciones,
    )
    if conciliacion is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    return ActualizarConciliacionResponse(
        codreclamo=request.codreclamo,
        propuesta_reclamante=conciliacion.propuesta_reclamante,
        puntos_acuerdo=conciliacion.puntos_acuerdo,
        puntos_desacuerdo=conciliacion.puntos_desacuerdo,
        observaciones=conciliacion.observaciones,
    )
