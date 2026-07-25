"""Servicio de aplicación para la resolución: genera y actualiza la
resolución final del reclamo a partir del veredicto ya fijado en el informe."""

import time
import logging

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from app.src.infrastructure.api_rest.schemas.investigacion import (
    ResolucionRequest, ResolucionResponse,
    ActualizarResolucionTextoRequest, ActualizarResolucionTextoResponse,
)
from app.src.application.usecase.agents.resolucion import ResolucionAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.llm.llm_router_service import LlmRouterService

logger = logging.getLogger("service.resolucion")


async def generar_resolucion_final(request: ResolucionRequest, llm_router: LlmRouterService) -> ResolucionResponse:
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

    # Caso normal: el frontend solo manda codreclamo. Se usan los datos de
    # conciliación ya guardados en el informe (propuesta generada por
    # POST /conciliacion/propuesta + los demás campos editados en
    # PATCH /conciliacion/datos). Solo se sobreescriben si el request trae un
    # valor explícito para ese campo puntual.
    conciliacion = informe.propuesta_conciliacion
    propuesta_empresa = request.propuesta_conciliacion or (conciliacion.propuesta_empresa if conciliacion else None)
    if not propuesta_empresa:
        raise HTTPException(
            status_code=409,
            detail=(
                "No hay propuesta de conciliación registrada para este reclamo. "
                "Genere la propuesta (POST /conciliacion/propuesta) antes de la resolución."
            ),
        )
    propuesta_reclamante = request.propuesta_reclamante or (conciliacion.propuesta_reclamante if conciliacion else None)
    observaciones = request.observaciones or (conciliacion.observaciones if conciliacion else None)

    resolucion_agent = ResolucionAgent(llm_router=llm_router, model=request.modelo)
    resultado = await run_in_threadpool(
        resolucion_agent.generar_resolucion,
        informe, propuesta_empresa, propuesta_reclamante, observaciones,
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


def actualizar_resolucion_texto(request: ActualizarResolucionTextoRequest) -> ActualizarResolucionTextoResponse:
    """Edita a mano el texto de la resolución, sin invocar al LLM."""
    actualizado = informe_store.actualizar_resolucion(request.codreclamo, request.resolucion)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    return ActualizarResolucionTextoResponse(codreclamo=request.codreclamo, resolucion=request.resolucion)
