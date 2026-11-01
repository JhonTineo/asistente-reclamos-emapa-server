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
    GuardarConciliacionRequest,
)
from app.src.application.usecase.agents.conciliador import ConciliadorAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.llm.llm_router_service import LlmRouterService
from app.src.core.model.conciliacion import Conciliacion
from app.src.application.services.informe.formatos import (
    propuesta_conciliacion, resultado_conciliacion, DATOS_POR_RESULTADO,
)

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
    if (informe.estado_evaluacion != "completada"
            or not informe.conclusion or not informe.veredicto):
        raise HTTPException(
            status_code=409,
            detail=(
                "No existe una decisión vigente y completa. Revise el estado "
                "de evaluación antes de generar la propuesta."
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
    conciliacion = informe.propuesta_conciliacion
    # La IA solo redacta el sustento; el texto se arma con el formato de EMAPA
    # (058-2023, DNI, mes reclamado, artículos citados y cierre según el
    # resultado de la audiencia, si ya se registró).
    conciliacion.sustento = resultado["propuesta"]
    conciliacion.propuesta_empresa = propuesta_conciliacion(informe, conciliacion.sustento, conciliacion)
    conciliacion.propuesta_editada = False
    resultado["propuesta"] = conciliacion.propuesta_empresa

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


def _aplicar_resultado(codreclamo: str, request) -> tuple[Conciliacion | None, bool]:
    """Guarda los datos de la conciliación y, si cambió el resultado de la
    audiencia, rearma el texto de la propuesta con el cierre que corresponde.
    No pisa un texto editado a mano, salvo que se pida `reaplicar_formato`.
    Devuelve (conciliacion, propuesta_regenerada)."""
    informe = informe_store.obtener(codreclamo)
    antes = resultado_conciliacion(informe.propuesta_conciliacion) if informe else "pendiente"
    conciliacion = informe_store.actualizar_conciliacion(
        codreclamo,
        propuesta_reclamante=request.propuesta_reclamante,
        puntos_acuerdo=request.puntos_acuerdo,
        puntos_desacuerdo=request.puntos_desacuerdo,
        observaciones=request.observaciones,
        asistio=getattr(request, "asistio", None),
        subsiste=getattr(request, "subsiste", None),
        por_telefono=getattr(request, "por_telefono", None),
        fecha_audiencia=getattr(request, "fecha_audiencia", None),
    )
    if conciliacion is None:
        return None, False
    despues = resultado_conciliacion(conciliacion)
    if despues != antes and despues in DATOS_POR_RESULTADO:
        postura, acuerdo, desacuerdo = DATOS_POR_RESULTADO[despues]
        if request.propuesta_reclamante is None:
            conciliacion.propuesta_reclamante = postura
        if request.puntos_acuerdo is None:
            conciliacion.puntos_acuerdo = acuerdo
        if request.puntos_desacuerdo is None:
            conciliacion.puntos_desacuerdo = desacuerdo
    regenerar = conciliacion.sustento and (
        getattr(request, "reaplicar_formato", False)
        or (despues != antes and not conciliacion.propuesta_editada)
    )
    if regenerar:
        conciliacion.propuesta_empresa = propuesta_conciliacion(informe, conciliacion.sustento, conciliacion)
        conciliacion.propuesta_editada = False
    return conciliacion, bool(regenerar)


def _respuesta(codreclamo: str, conciliacion: Conciliacion, regenerada: bool) -> ActualizarConciliacionResponse:
    return ActualizarConciliacionResponse(
        codreclamo=codreclamo,
        propuesta_reclamante=conciliacion.propuesta_reclamante,
        puntos_acuerdo=conciliacion.puntos_acuerdo,
        puntos_desacuerdo=conciliacion.puntos_desacuerdo,
        observaciones=conciliacion.observaciones,
        asistio=conciliacion.asistio,
        subsiste=conciliacion.subsiste,
        por_telefono=conciliacion.por_telefono,
        fecha_audiencia=conciliacion.fecha_audiencia,
        resultado=resultado_conciliacion(conciliacion),
        propuesta_empresa=conciliacion.propuesta_empresa,
        propuesta_editada=conciliacion.propuesta_editada,
        propuesta_regenerada=regenerada,
    )


def actualizar_conciliacion(request: ActualizarConciliacionRequest) -> ActualizarConciliacionResponse:
    """Edita a mano los demás datos de la conciliación (postura del
    reclamante, puntos de acuerdo/desacuerdo, observaciones) y el resultado de
    la audiencia (asistió, ¿subsiste el reclamo?, por teléfono, fecha), sin
    invocar al LLM. Solo pisa los campos que vengan en el request."""
    conciliacion, regenerada = _aplicar_resultado(request.codreclamo, request)
    if not conciliacion:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    return _respuesta(request.codreclamo, conciliacion, regenerada)


def guardar_conciliacion(request: GuardarConciliacionRequest) -> ActualizarConciliacionResponse:
    """Guarda todos los campos de la conciliación en una sola petición."""
    # Primero guardamos la propuesta de la empresa
    if request.propuesta_empresa is not None:
        informe_store.actualizar_propuesta(request.codreclamo, request.propuesta_empresa)
    
    # Luego los demás datos (y el resultado de la audiencia, si viene)
    conciliacion, regenerada = _aplicar_resultado(request.codreclamo, request)

    if not conciliacion and request.propuesta_empresa is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    if conciliacion is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    return _respuesta(request.codreclamo, conciliacion, regenerada)
