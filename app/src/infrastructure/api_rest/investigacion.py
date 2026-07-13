import time
import logging
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
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
    ProblemaNormadoSchema,
    InformeRequest,
    InformeResponse,
    ProblemaInforme,
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
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
from app.src.core.service.tools.emapa_client import consultar_emapa

from app.src.application.usecase.agents.analista_medio import AnalistaMedioAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe
from app.src.core.model.informe_atencion import BloqueMedio


logger = logging.getLogger("api.investigacion")

router = APIRouter(prefix="", tags=["investigacion"])


def _analizar_medio_y_registrar(
    request: BuscarReclamoRequest,
    medio_id: str,
    medio_nombre: str,
) -> ResumenMedio:
    """Analiza un medio, registra su bloque en el informe (store) y devuelve
    el ResumenMedio con los problemas detectados (aún sin fundamentar)."""
    t_inicio = time.perf_counter()
    logger.info("=" * 60)
    logger.info(
        "[API /investigacion/%s] codsuc=%s | codcliente=%s | codreclamo=%s",
        medio_id, request.codsuc, request.codcliente, request.codreclamo,
    )

    analista = AnalistaMedioAgent(model=request.modelo)
    bloque = analista.analizar(
        medio_id=medio_id,
        medio_nombre=medio_nombre,
        codsuc=request.codsuc,
        codcliente=request.codcliente,
        clasificacion=request.clasificacion,
    )

    informe_store.registrar_bloque(
        codreclamo=request.codreclamo,
        bloque=bloque,
        suministro=request.codcliente,
        clasificacion=request.clasificacion,
    )

    tiempo_total = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/%s] COMPLETADO | problemas=%d | tiempo=%.2fs",
        medio_id, len(bloque.problemas), tiempo_total,
    )
    logger.info("=" * 60)

    return ResumenMedio(
        medio_id=bloque.medio_id,
        medio_nombre=bloque.medio_nombre,
        datos=bloque.entidad,
        resumen=bloque.resumen,
        problemas=[ProblemaNormadoSchema(**vars(p)) for p in bloque.problemas],
        tiempo=tiempo_total,
    )

def _stream_analisis_medio(
    request: BuscarReclamoRequest,
    medio_id: str,
    medio_nombre: str,
) -> StreamingResponse:
    """Analiza un medio en streaming (NDJSON). Emite dos eventos:

    1. ``preprocesamiento``: datos y problemas por reglas (sale de inmediato).
    2. ``resumen``: interpretación del LLM en lenguaje natural (sale al final).

    El bloque se registra en el informe recién cuando se tiene el resumen.
    """

    async def generador():
        t_inicio = time.perf_counter()
        logger.info("=" * 60)
        logger.info(
            "[API /investigacion/%s/stream] codsuc=%s | codcliente=%s | codreclamo=%s",
            medio_id, request.codsuc, request.codcliente, request.codreclamo,
        )
        analista = AnalistaMedioAgent(model=request.modelo)

        try:
            # --- Fase 1: preprocesamiento (rápido) ---------------------------
            datos, problemas = await run_in_threadpool(
                analista.preprocesar,
                medio_id, medio_nombre, request.codsuc, request.codcliente,
            )
            problemas_schema = [ProblemaNormadoSchema(**vars(p)) for p in problemas]
            evento_pre = {
                "evento": "preprocesamiento",
                "medio_id": medio_id,
                "medio_nombre": medio_nombre,
                "datos": datos,
                "problemas": [p.model_dump() for p in problemas_schema],
                "tiempo": time.perf_counter() - t_inicio,
            }
            yield json.dumps(evento_pre, ensure_ascii=False) + "\n"

            # --- Fase 2: interpretación LLM (lento) --------------------------
            resumen = await run_in_threadpool(
                analista.interpretar,
                medio_id, medio_nombre, datos, problemas, request.clasificacion,
            )

            bloque = BloqueMedio(
                medio_id=medio_id,
                medio_nombre=medio_nombre,
                entidad=datos,
                resumen=resumen,
                problemas=problemas,
            )
            informe_store.registrar_bloque(
                codreclamo=request.codreclamo,
                bloque=bloque,
                suministro=request.codcliente,
                clasificacion=request.clasificacion,
            )

            tiempo_total = time.perf_counter() - t_inicio
            evento_res = {
                "evento": "resumen",
                "medio_id": medio_id,
                "resumen": resumen,
                "tiempo": tiempo_total,
            }
            yield json.dumps(evento_res, ensure_ascii=False) + "\n"

            logger.info(
                "[API /investigacion/%s/stream] COMPLETADO | problemas=%d | tiempo=%.2fs",
                medio_id, len(problemas), tiempo_total,
            )
            logger.info("=" * 60)
        except Exception as e:  # noqa: BLE001
            logger.exception("[API /investigacion/%s/stream] ERROR", medio_id)
            evento_err = {
                "evento": "error",
                "medio_id": medio_id,
                "error": str(e),
            }
            yield json.dumps(evento_err, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")


@router.post("/investigacion/inspeccion-externa/stream")
async def inspeccion_externa_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM."""
    return _stream_analisis_medio(request, "inspeccion_externa", "Inspección Externa")


@router.post("/investigacion/inspeccion-interna/stream")
async def inspeccion_interna_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM."""
    return _stream_analisis_medio(request, "inspeccion_interna", "Inspección Interna")


@router.post("/investigacion/tarjeta-lectura/stream")
async def tarjeta_lectura_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM."""
    return _stream_analisis_medio(request, "tarjeta_lectura", "Tarjeta de Lecturas")


@router.post("/investigacion/corte-reapertura/stream")
async def corte_reapertura_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM."""
    return _stream_analisis_medio(request, "corte_reapertura", "Cortes y Reaperturas")


@router.post("/investigacion/inspeccion-externa", response_model=ResumenMedio)
async def inspeccion_externa(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección externa y registra su bloque en el informe."""
    return _analizar_medio_y_registrar(request, "inspeccion_externa", "Inspección Externa")


@router.post("/investigacion/inspeccion-interna", response_model=ResumenMedio)
async def inspeccion_interna(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección interna y registra su bloque en el informe."""
    return _analizar_medio_y_registrar(request, "inspeccion_interna", "Inspección Interna")


@router.post("/investigacion/tarjeta-lectura", response_model=ResumenMedio)
async def tarjeta_lectura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la tarjeta de lecturas (micromedición) y registra su bloque."""
    return _analizar_medio_y_registrar(request, "tarjeta_lectura", "Tarjeta de Lecturas")


@router.post("/investigacion/corte-reapertura", response_model=ResumenMedio)
async def corte_reapertura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza los cortes/reaperturas y registra su bloque en el informe.
    Requiere que se haya analizado antes la tarjeta de lecturas (fija la ventana)."""
    return _analizar_medio_y_registrar(request, "corte_reapertura", "Cortes y Reaperturas")


@router.post("/investigacion/informe", response_model=InformeResponse)
async def generar_informe(request: InformeRequest) -> InformeResponse:
    """
    Cierra el informe de atención: recupera el informe (con los bloques ya
    llenados por cada medio), fundamenta normativamente cada problema
    detectado y devuelve el texto final en lenguaje natural.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /investigacion/informe] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                "Busque el reclamo y analice al menos un medio antes de generarlo."
            ),
        )

    clasificacion = request.clasificacion or informe.clasificacion or ""

    # Fase 4: fundamentación normativa de cada problema de cada bloque.
    fundamentador = FundamentacionNormativaAgent(model=request.modelo)
    problemas_resp: list[ProblemaInforme] = []
    for bloque in informe.bloques:
        for problema in bloque.problemas:
            fundamentador.fundamentar(problema, clasificacion)
            problemas_resp.append(
                ProblemaInforme(
                    medio_id=bloque.medio_id,
                    tipo=problema.tipo,
                    detalle=problema.detalle,
                    accion=problema.accion,
                    responsable=problema.responsable,
                    base_legal=problema.base_legal,
                )
            )

    texto = construir_texto_informe(informe)

    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/informe] COMPLETADO | bloques=%d | problemas=%d | tiempo=%.2fs",
        len(informe.bloques), len(problemas_resp), tiempo,
    )
    logger.info("=" * 60)

    return InformeResponse(
        codreclamo=request.codreclamo,
        informe=texto,
        problemas=problemas_resp,
        tiempo=tiempo,
    )


@router.post("/investigacion/informe/stream")
async def generar_informe_stream(request: InformeRequest) -> StreamingResponse:
    """Cierra el informe en streaming (NDJSON). Por cada problema de cada medio
    emite dos eventos a medida que se producen:

    1. ``articulos``: los artículos SUNASS recuperados para ese problema.
    2. ``fundamentacion``: la inferencia del LLM (acción, responsable, base legal).

    Al final emite ``informe`` con el texto en lenguaje natural ya armado.
    """

    async def generador():
        t_inicio = time.perf_counter()
        logger.info("=" * 60)
        logger.info("[API /investigacion/informe/stream] codreclamo=%s", request.codreclamo)

        informe = informe_store.obtener(request.codreclamo)
        if informe is None:
            yield json.dumps({
                "evento": "error",
                "error": (
                    f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                    "Busque el reclamo y analice al menos un medio antes de generarlo."
                ),
            }, ensure_ascii=False) + "\n"
            return

        clasificacion = request.clasificacion or informe.clasificacion or ""

        # Total de problemas (para que el frontend muestre progreso).
        total = sum(len(b.problemas) for b in informe.bloques)
        yield json.dumps({"evento": "inicio", "total_problemas": total}, ensure_ascii=False) + "\n"

        fundamentador = FundamentacionNormativaAgent(model=request.modelo)
        problemas_resp: list[ProblemaInforme] = []
        indice = 0

        try:
            for bloque in informe.bloques:
                for problema in bloque.problemas:
                    # --- Fase 1: recuperación de artículos -------------------
                    articulos = await run_in_threadpool(
                        fundamentador.fundamentar_articulos, problema
                    )
                    yield json.dumps({
                        "evento": "articulos",
                        "indice": indice,
                        "medio_id": bloque.medio_id,
                        "tipo": problema.tipo,
                        "detalle": problema.detalle,
                        "articulos": problema.articulos,
                    }, ensure_ascii=False) + "\n"

                    # --- Fase 2: inferencia del LLM --------------------------
                    await run_in_threadpool(
                        fundamentador.fundamentar_interpretacion,
                        problema, articulos, clasificacion,
                    )
                    yield json.dumps({
                        "evento": "fundamentacion",
                        "indice": indice,
                        "medio_id": bloque.medio_id,
                        "tipo": problema.tipo,
                        "detalle": problema.detalle,
                        "accion": problema.accion,
                        "responsable": problema.responsable,
                        "base_legal": problema.base_legal,
                    }, ensure_ascii=False) + "\n"

                    problemas_resp.append(
                        ProblemaInforme(
                            medio_id=bloque.medio_id,
                            tipo=problema.tipo,
                            detalle=problema.detalle,
                            accion=problema.accion,
                            responsable=problema.responsable,
                            base_legal=problema.base_legal,
                        )
                    )
                    indice += 1

            # --- Cierre: texto final del informe ------------------------------
            texto = construir_texto_informe(informe)
            tiempo = time.perf_counter() - t_inicio
            yield json.dumps({
                "evento": "informe",
                "codreclamo": request.codreclamo,
                "informe": texto,
                "problemas": [p.model_dump() for p in problemas_resp],
                "tiempo": tiempo,
            }, ensure_ascii=False) + "\n"

            logger.info(
                "[API /investigacion/informe/stream] COMPLETADO | bloques=%d | problemas=%d | tiempo=%.2fs",
                len(informe.bloques), len(problemas_resp), tiempo,
            )
            logger.info("=" * 60)
        except Exception as e:  # noqa: BLE001
            logger.exception("[API /investigacion/informe/stream] ERROR")
            yield json.dumps({"evento": "error", "error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")


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


