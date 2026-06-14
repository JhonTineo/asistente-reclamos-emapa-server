import time
import logging
from fastapi import APIRouter
from app.schemas.investigacion import (
    InvestigacionRequest,
    InvestigacionResponse,
    ResumenMedio,
    InformeRequest,
    InformeResponse,
)
from app.agent.coordinator import analizar_medios
from app.agent.unificador import UnificadorAgent

logger = logging.getLogger("api.investigacion")

router = APIRouter(prefix="/investigacion", tags=["investigacion"])


@router.post("/iniciar", response_model=InvestigacionResponse)
async def iniciar_investigacion(request: InvestigacionRequest) -> InvestigacionResponse:
    """
    Obtiene y analiza todos los medios probatorios en paralelo.
    Retorna los resumenes de cada medio para que el usuario los verifique.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /iniciar] Solicitud recibida")
    logger.info("[API /iniciar] codsuc=%s | codcliente=%s | codreclamo=%s",
                request.codsuc, request.codcliente, request.codreclamo)
    logger.info("[API /iniciar] clasificacion=%s | anio=%s", request.clasificacion, request.anio)
    logger.info("[API /iniciar] detalle=%s", request.detalle[:100] + "..." if len(request.detalle) > 100 else request.detalle)

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

    logger.info("[API /iniciar] Enviando respuesta al cliente...")
    logger.info("[API /iniciar] Resumenes enviados: %d", len(resumenes_response))
    for r in resumenes_response:
        logger.info("[API /iniciar]   - %s: %s", r.medio_nombre, r.estado)
    logger.info("[API /iniciar] COMPLETADO | tiempo_total=%.2fs", tiempo_total)
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


@router.post("/informe", response_model=InformeResponse)
async def generar_informe(request: InformeRequest) -> InformeResponse:
    """
    Genera el informe final a partir de los resumenes verificados por el usuario.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /informe] Solicitud recibida")
    logger.info("[API /informe] codreclamo=%s | clasificacion=%s", request.codreclamo, request.clasificacion)
    logger.info("[API /informe] Resumenes verificados por usuario: %d", len(request.resumenes))

    for i, r in enumerate(request.resumenes, 1):
        logger.info("[API /informe]   %d. %s: %s", i, r.medio_nombre, r.estado)
        if r.resumen:
            logger.info("[API /informe]      Resumen: %s", (r.resumen[:60] + "...") if len(r.resumen) > 60 else r.resumen)

    unificador = UnificadorAgent(model=request.modelo)
    resultado = unificador.generar_informe(
        codreclamo=request.codreclamo,
        clasificacion=request.clasificacion,
        detalle=request.detalle,
        resumenes=[r.model_dump() for r in request.resumenes],
    )

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /informe] Informe generado (%d caracteres)", len(resultado["informe"]))
    logger.info("[API /informe] COMPLETADO | tiempo=%.2fs", tiempo)
    logger.info("=" * 60)

    return InformeResponse(
        codreclamo=request.codreclamo,
        informe=resultado["informe"],
        tiempo=tiempo,
    )
