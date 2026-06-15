import time
import logging
import json
from fastapi import APIRouter
from app.schemas.investigacion import (
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
from app.agent.coordinator import analizar_medios
from app.agent.unificador import UnificadorAgent
from app.agent.conciliador import ConciliadorAgent
from app.agent.resolucion import ResolucionAgent
from app.tools.emapa_client import consultar_emapa

logger = logging.getLogger("api.investigacion")

router = APIRouter(prefix="", tags=["investigacion"])


@router.post("/investigacion/iniciar", response_model=InvestigacionResponse)
async def iniciar_investigacion(request: InvestigacionRequest) -> InvestigacionResponse:
    """
    Obtiene y analiza todos los medios probatorios en paralelo.
    Retorna los resumenes de cada medio para que el usuario los verifique.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /investigacion/iniciar] Solicitud recibida")
    logger.info("[API /investigacion/iniciar] codsuc=%s | codcliente=%s | codreclamo=%s",
                request.codsuc, request.codcliente, request.codreclamo)
    logger.info("[API /investigacion/iniciar] clasificacion=%s | anio=%s", request.clasificacion, request.anio)
    logger.info("[API /investigacion/iniciar] detalle=%s", request.detalle[:100] + "..." if len(request.detalle) > 100 else request.detalle)

    resumenes = await analizar_medios(
        codsuc=request.codsuc,
        codcliente=request.codcliente,
        codreclamo=request.codreclamo,
        clasificacion=request.clasificacion,
        anio=request.anio,
        modelo=request.modelo,
    )

    tiempo_total = time.perf_counter() - t_inicio
    resumenes_response = [ResumenMedio(**r) for r in resumenes]

    logger.info("[API /investigacion/iniciar] COMPLETADO | tiempo_total=%.2fs", tiempo_total)
    logger.info("=" * 60)

    return InvestigacionResponse(
        codreclamo=request.codreclamo,
        codsuc=request.codsuc,
        codcliente=request.codcliente,
        clasificacion=request.clasificacion,
        detalle=request.detalle,
        resumenes=resumenes_response,
        tiempo_total=tiempo_total,
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


@router.get("/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}", response_model=BuscarReclamoResponse)
async def buscar_reclamo(codsede: str, codsuc: str, codreclamo: str, codcliente: str) -> BuscarReclamoResponse:
    """
    Busca los datos de un reclamo en el sistema de EMAPA.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /reclamo] Buscando reclamo")
    logger.info("[API /reclamo] codsede=%s | codsuc=%s | codcliente=%s | codreclamo=%s",
                codsede, codsuc, codcliente, codreclamo)

    result = consultar_emapa(
        endpoint_key="buscar_reclamo",
        params={"codsede": codsede, "codsuc": codsuc, "codreclamo": codreclamo, "codcliente": codcliente}
    )

    tiempo = time.perf_counter() - t_inicio

    if result.success:
        try:
            datos = json.loads(result.data) if result.data else None
            logger.info("[API /reclamo] OK | tiempo=%.2fs", tiempo)
            logger.info("=" * 60)
            return BuscarReclamoResponse(
                codreclamo=codreclamo,
                datos=datos,
                tiempo=tiempo,
            )
        except json.JSONDecodeError as e:
            logger.error("[API /reclamo] Error al parsear respuesta: %s", str(e))
            logger.info("=" * 60)
            return BuscarReclamoResponse(
                codreclamo=codreclamo,
                datos=None,
                error=f"Error al parsear respuesta: {str(e)}",
                tiempo=tiempo,
            )
    else:
        logger.error("[API /reclamo] Error: %s", result.error)
        logger.info("=" * 60)
        return BuscarReclamoResponse(
            codreclamo=codreclamo,
            datos=None,
            error=result.error,
            tiempo=tiempo,
        )
