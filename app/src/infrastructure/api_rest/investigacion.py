import time
import logging
import json
from fastapi import APIRouter
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.core.service.tools.emapa_api import (
    buscar_reclamo_emapa,
    obtener_saldo_actual,
    obtener_tarjeta_lectura,
    obtener_record_facturacion,
    obtener_corte_reapertura,
    obtener_inspeccion_externa,
    obtener_inspeccion_interna,
)
from app.src.core.schemas.investigacion import (
    InvestigacionRequest,
    InvestigacionResponse,
    ResumenMedio,
    InformeRequest,
    InformeResponse,
    ConciliacionRequest,
    ConciliacionResponse,
    ResolucionRequest,
    ResolucionResponse,
    BuscarReclamoRequest,
    BuscarReclamoResponse,
)
from app.src.application.usecase.agents.unificador import UnificadorAgent
from app.src.application.usecase.agents.conciliador import ConciliadorAgent
from app.src.application.usecase.agents.resolucion import ResolucionAgent
from app.src.core.service.tools.emapa_client import consultar_emapa

from app.src.application.usecase.agents.analista_medio import AnalistaMedioAgent


logger = logging.getLogger("api.investigacion")

router = APIRouter(prefix="", tags=["investigacion"])

@router.post("/investigacion/inspeccion-externa", response_model=ResumenMedio)
async def inspeccion_externa(request: BuscarReclamoRequest) -> ResumenMedio:
    """Genera un resumen de la inspección externa para un reclamo específico."""
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info("[API /investigacion/inspeccion-externa] Solicitud recibida codsuc=%s | codcliente=%s | codreclamo=%s", request.codsuc, request.codcliente, request.codreclamo)
    analista = AnalistaMedioAgent(model=request.modelo)
    resultado = analista.analizar(
        medio_id="inspeccion_externa",
        medio_nombre="Inspección Externa",
        codsuc=request.codsuc,
        codcliente=request.codcliente,
        clasificacion=request.clasificacion,
    )
    tiempo_total = time.perf_counter() - t_inicio
    logger.info("[API /investigacion/inspeccion-externa] COMPLETADO | tiempo_total=%.2fs", tiempo_total)
    logger.info("=" * 60)
    return ResumenMedio(
        medio_id="inspeccion_externa",
        medio_nombre="Inspección Externa",
        resumen=resultado.analisis,
        tiempo=tiempo_total,
    )


@router.post("/investigacion/inspeccion-interna", response_model=ResumenMedio)
async def inspeccion_interna(request: BuscarReclamoRequest) -> ResumenMedio:
    """Genera un resumen de la inspección interna para un reclamo específico."""
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info("[API /investigacion/inspeccion-interna] Solicitud recibida codsuc=%s | codcliente=%s | codreclamo=%s", request.codsuc, request.codcliente, request.codreclamo)
    analista = AnalistaMedioAgent(model=request.modelo)
    resultado = analista.analizar(
        medio_id="inspeccion_interna",
        medio_nombre="Inspección Interna",
        codsuc=request.codsuc,
        codcliente=request.codcliente,
        clasificacion=request.clasificacion,
    )
    tiempo_total = time.perf_counter() - t_inicio
    logger.info("[API /investigacion/inspeccion-interna] COMPLETADO | tiempo_total=%.2fs", tiempo_total)
    logger.info("=" * 60)
    return ResumenMedio(
        medio_id="inspeccion_interna",
        medio_nombre="Inspección Interna",
        resumen=resultado.analisis,
        tiempo=tiempo_total,
    )


@router.post("/investigacion/informe", response_model=InformeResponse)
async def generar_informe(request: InformeRequest) -> InformeResponse:
    """
    Genera el informe final a partir de los resumenes verificados por el usuario.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /investigacion/informe] Solicitud recibida")
    logger.info("[API /investigacion/informe] codreclamo=%s", request.codreclamo)

    unificador = UnificadorAgent(model=request.modelo)
    resultado = unificador.generar_informe(
        codreclamo=request.codreclamo,
        clasificacion=request.clasificacion,
        detalle=request.detalle,
        resumenes=[r.model_dump() for r in request.resumenes],
    )

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /investigacion/informe] COMPLETADO | tiempo=%.2fs", tiempo)
    logger.info("=" * 60)

    return InformeResponse(
        codreclamo=request.codreclamo,
        informe=resultado["informe"],
        tiempo=tiempo,
    )


@router.post("/conciliacion/propuesta", response_model=ConciliacionResponse)
async def generar_propuesta(request: ConciliacionRequest) -> ConciliacionResponse:
    """
    Genera la propuesta de conciliación a partir del informe de atención.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /conciliacion/propuesta] Solicitud recibida")
    logger.info("[API /conciliacion/propuesta] codreclamo=%s | clasificacion=%s",
                request.codreclamo, request.clasificacion)
    logger.info("[API /conciliacion/propuesta] Longitud informe: %d caracteres", len(request.informe_atencion))

    conciliador = ConciliadorAgent(model=request.modelo)
    resultado = conciliador.generar_propuesta(
        codreclamo=request.codreclamo,
        clasificacion=request.clasificacion,
        informe_atencion=request.informe_atencion,
    )

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /conciliacion/propuesta] COMPLETADO | tiempo=%.2fs", tiempo)
    logger.info("=" * 60)

    return ConciliacionResponse(
        codreclamo=request.codreclamo,
        propuesta=resultado["propuesta"],
        tiempo=tiempo,
    )


@router.post("/resolucion", response_model=ResolucionResponse)
async def generar_resolucion(request: ResolucionRequest) -> ResolucionResponse:
    """
    Genera la resolución final del reclamo (fundada o infundada).
    El modelo determina automáticamente si es fundada o infundada.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /resolucion] Solicitud recibida")
    logger.info("[API /resolucion] codreclamo=%s", request.codreclamo)

    resolucion_agent = ResolucionAgent(model=request.modelo)
    resultado = resolucion_agent.generar_resolucion(
        codreclamo=request.codreclamo,
        informe_atencion=request.informe_atencion,
        propuesta_conciliacion=request.propuesta_conciliacion,
        observaciones=request.observaciones,
    )

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /resolucion] COMPLETADO | tipo=%s | tiempo=%.2fs", resultado["tipo"], tiempo)
    logger.info("=" * 60)

    return ResolucionResponse(
        codreclamo=request.codreclamo,
        tipo=resultado["tipo"],
        resolucion=resultado["resolucion"],
        tiempo=tiempo,
    )


