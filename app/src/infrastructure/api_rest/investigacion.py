import time
import asyncio
import logging
import json
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from app.src.infrastructure.api_rest.deps import usar_token_emapa, asegurar_token_emapa
from starlette.concurrency import run_in_threadpool
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.infrastructure.api_rest.schemas.investigacion import (
    InvestigacionRequest,
    InvestigacionResponse,
    ResumenMedio,
    ProblemaNormadoSchema,
    InformeRequest,
    InformeResponse,
    InformePreviewRequest,
    InformePreviewResponse,
    ProblemaInforme,
    ConciliacionRequest,
    ConciliacionResponse,
    ResolucionRequest,
    ResolucionResponse,
    BuscarReclamoRequest,
    BuscarReclamoResponse,
    ObjetivosRequest,
    ObjetivosResponse,
    ObjetivoInvestigacionSchema,
    MediosDisponiblesRequest,
    MediosDisponiblesResponse,
    MedioDisponible,
)
from app.src.application.usecase.agents.conciliador import ConciliadorAgent
from app.src.application.usecase.agents.resolucion import ResolucionAgent
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
from app.src.application.usecase.agents.objetivos import ObjetivosAgent
from app.src.application.usecase.agents.conclusion import ConclusionAgent

from app.src.application.usecase.agents.analista_medio import AnalistaMedioAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.application.services.informe.render import construir_texto_informe
from app.src.core.model.informe_atencion import BloqueMedio
from app.src.application.adapters.emapa_api import (
    obtener_tarjeta_lectura,
    obtener_corte_reapertura,
    obtener_inspeccion_externa,
    obtener_inspeccion_interna,
    obtener_record_facturacion,
    obtener_saldo_actual,
)


logger = logging.getLogger("api.investigacion")

router = APIRouter(prefix="", tags=["investigacion"], dependencies=[Depends(usar_token_emapa)])


async def _analizar_medio_y_registrar(
    request: BuscarReclamoRequest,
    medio_id: str,
    medio_nombre: str,
) -> ResumenMedio:
    """Analiza un medio, registra su bloque en el informe (store) y devuelve
    el ResumenMedio con los problemas detectados (aún sin fundamentar)."""
    t_inicio = time.perf_counter()
    # Usa el token de la petición o, si no vino, el guardado al buscar el reclamo.
    await asegurar_token_emapa(request.codreclamo)
    logger.info("=" * 60)
    logger.info(
        "[API /investigacion/%s] codsuc=%s | codcliente=%s | codreclamo=%s",
        medio_id, request.codsuc, request.codcliente, request.codreclamo,
    )

    # Lee la ventana actual del informe (si existe).
    informe = informe_store.obtener(request.codreclamo)
    ventana_actual = informe.ventana_meses if informe else []

    analista = AnalistaMedioAgent(model=request.modelo)
    bloque, ventana = analista.analizar(
        medio_id=medio_id,
        medio_nombre=medio_nombre,
        codsuc=request.codsuc,
        codcliente=request.codcliente,
        clasificacion=request.clasificacion,
        meses=request.meses,
        ventana=ventana_actual,
    )

    informe = informe_store.registrar_bloque(
        codreclamo=request.codreclamo,
        bloque=bloque,
        suministro=request.codcliente,
        clasificacion=request.clasificacion,
    )
    # Persiste la ventana devuelta (solo la tarjeta la actualiza).
    if ventana:
        informe.ventana_meses = ventana

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
        # Usa el token de la petición o, si no vino, el guardado al buscar el
        # reclamo. Debe fijarse aquí, antes de las llamadas en threadpool, para
        # que el ContextVar se propague al hilo que consulta EMAPA.
        await asegurar_token_emapa(request.codreclamo)
        logger.info("=" * 60)
        logger.info(
            "[API /investigacion/%s/stream] codsuc=%s | codcliente=%s | codreclamo=%s",
            medio_id, request.codsuc, request.codcliente, request.codreclamo,
        )

        # Lee la ventana actual del informe (si existe).
        informe = informe_store.obtener(request.codreclamo)
        ventana_actual = informe.ventana_meses if informe else []

        analista = AnalistaMedioAgent(model=request.modelo)

        try:
            # --- Fase 1: preprocesamiento (rápido) ---------------------------
            datos, problemas, ventana = await run_in_threadpool(
                analista.preprocesar,
                medio_id, medio_nombre, request.codsuc, request.codcliente,
                request.meses, ventana_actual,
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
            informe = informe_store.registrar_bloque(
                codreclamo=request.codreclamo,
                bloque=bloque,
                suministro=request.codcliente,
                clasificacion=request.clasificacion,
            )
            # Persiste la ventana devuelta (solo la tarjeta la actualiza).
            if ventana:
                informe.ventana_meses = ventana

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


@router.post("/investigacion/record-facturacion/stream")
async def record_facturacion_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM."""
    return _stream_analisis_medio(request, "record_facturacion", "Record de Facturación")


@router.post("/investigacion/saldo-detalle/stream")
async def saldo_detalle_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM."""
    return _stream_analisis_medio(request, "saldo_detalle", "Saldo Detalle")


@router.post("/investigacion/inspeccion-externa", response_model=ResumenMedio)
async def inspeccion_externa(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección externa y registra su bloque en el informe."""
    return await _analizar_medio_y_registrar(request, "inspeccion_externa", "Inspección Externa")


@router.post("/investigacion/inspeccion-interna", response_model=ResumenMedio)
async def inspeccion_interna(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección interna y registra su bloque en el informe."""
    return await _analizar_medio_y_registrar(request, "inspeccion_interna", "Inspección Interna")


@router.post("/investigacion/tarjeta-lectura", response_model=ResumenMedio)
async def tarjeta_lectura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la tarjeta de lecturas (micromedición) y registra su bloque."""
    return await _analizar_medio_y_registrar(request, "tarjeta_lectura", "Tarjeta de Lecturas")


@router.post("/investigacion/corte-reapertura", response_model=ResumenMedio)
async def corte_reapertura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza los cortes/reaperturas y registra su bloque en el informe.
    Requiere que se haya analizado antes la tarjeta de lecturas (fija la ventana)."""
    return await _analizar_medio_y_registrar(request, "corte_reapertura", "Cortes y Reaperturas")


@router.post("/investigacion/record-facturacion", response_model=ResumenMedio)
async def record_facturacion(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza el record de facturación (cómo se facturó cada mes: por lectura o
    por promedio) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana de meses)."""
    return await _analizar_medio_y_registrar(request, "record_facturacion", "Record de Facturación")


@router.post("/investigacion/saldo-detalle", response_model=ResumenMedio)
async def saldo_detalle(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza el saldo-detalle (pagos por mes: cobro indebido, mora y meses
    pendientes) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana de meses)."""
    return await _analizar_medio_y_registrar(request, "saldo_detalle", "Saldo Detalle")


# Medios cuya disponibilidad se puede verificar (función EMAPA por medio).
# El orden define el orden de análisis en el frontend.
_MEDIOS_VERIFICABLES = {
    "tarjeta_lectura": lambda r: obtener_tarjeta_lectura(r.codsuc, r.codcliente),
    "record_facturacion": lambda r: obtener_record_facturacion(r.codsuc, r.codcliente, r.anio),
    "corte_reapertura": lambda r: obtener_corte_reapertura(r.codsuc, r.codcliente),
    "saldo_detalle": lambda r: obtener_saldo_actual(r.codsuc, r.codcliente),
    "saldo_actual": lambda r: obtener_saldo_actual(r.codsuc, r.codcliente),
    "inspeccion_externa": lambda r: obtener_inspeccion_externa(r.codsuc, r.codcliente),
    "inspeccion_interna": lambda r: obtener_inspeccion_interna(r.codsuc, r.codcliente),
}


def _tiene_datos(respuesta: dict) -> bool:
    """True si la respuesta de EMAPA trae datos utilizables (no 404/parcial ni vacío)."""
    if not isinstance(respuesta, dict) or respuesta.get("_partial"):
        return False
    return bool(respuesta.get("data"))


@router.post("/investigacion/objetivos", response_model=ObjetivosResponse)
async def generar_objetivos(request: ObjetivosRequest) -> ObjetivosResponse:
    """Genera los objetivos de investigación a partir del motivo del reclamo
    (guardado al buscar el reclamo) y los deja en el informe. Se llama aparte de
    la búsqueda para poder correrlo en paralelo con la verificación de medios."""
    t_inicio = time.perf_counter()
    logger.info("[API /investigacion/objetivos] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}. Busque el reclamo primero.",
        )

    motivo = (informe.motivo or "").strip()
    logger.info(
        "[API /investigacion/objetivos] motivo_len=%d | clasificacion=%s",
        len(motivo), informe.clasificacion,
    )
    if motivo:
        agente = ObjetivosAgent(model=request.modelo)
        informe.objetivos = await run_in_threadpool(agente.generar, motivo, informe.clasificacion or "")
    else:
        informe.objetivos = []
        logger.warning(
            "[API /investigacion/objetivos] Reclamo %s SIN motivo guardado; no se infieren objetivos. "
            "¿Se buscó el reclamo (que guarda el motivo) después de reiniciar el server?",
            request.codreclamo,
        )

    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/objetivos] COMPLETADO | objetivos=%d | tiempo=%.2fs",
        len(informe.objetivos), tiempo,
    )
    return ObjetivosResponse(
        codreclamo=request.codreclamo,
        objetivos=[ObjetivoInvestigacionSchema(**vars(o)) for o in informe.objetivos],
        tiempo=tiempo,
    )


@router.post("/investigacion/medios-disponibles", response_model=MediosDisponiblesResponse)
async def medios_disponibles(request: MediosDisponiblesRequest) -> MediosDisponiblesResponse:
    """Verifica en paralelo qué medios probatorios devuelven datos desde EMAPA,
    sin analizarlos (sin LLM). Sirve para marcar en el front los medios que sí
    traen información."""
    t_inicio = time.perf_counter()
    await asegurar_token_emapa(request.codreclamo)
    logger.info("[API /investigacion/medios-disponibles] codreclamo=%s", request.codreclamo)

    async def _verificar(medio_id: str, fn) -> MedioDisponible:
        try:
            respuesta = await run_in_threadpool(fn, request)
            return MedioDisponible(medio_id=medio_id, disponible=_tiene_datos(respuesta))
        except Exception as e:  # noqa: BLE001
            logger.warning("[MEDIOS] %s error=%s", medio_id, e)
            return MedioDisponible(medio_id=medio_id, disponible=False, error=str(e))

    medios = await asyncio.gather(
        *(_verificar(mid, fn) for mid, fn in _MEDIOS_VERIFICABLES.items())
    )

    tiempo = time.perf_counter() - t_inicio
    disponibles = sum(1 for m in medios if m.disponible)
    logger.info(
        "[API /investigacion/medios-disponibles] COMPLETADO | disponibles=%d/%d | tiempo=%.2fs",
        disponibles, len(medios), tiempo,
    )
    return MediosDisponiblesResponse(codreclamo=request.codreclamo, medios=list(medios), tiempo=tiempo)


@router.post("/investigacion/conclusion", response_model=InformeResponse)
async def generar_conclusion(request: InformeRequest) -> InformeResponse:
    """
    Concluye el informe de atención: recupera el informe (con los bloques ya
    llenados por cada medio), fundamenta normativamente cada problema
    detectado y devuelve el texto final en lenguaje natural.
    """
    t_inicio = time.perf_counter()

    logger.info("=" * 60)
    logger.info("[API /investigacion/conclusion] codreclamo=%s", request.codreclamo)

    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                "Busque el reclamo y analice al menos un medio antes de concluirlo."
            ),
        )

    clasificacion = request.clasificacion or informe.clasificacion or ""

    # Fase 4: fundamentación normativa de cada problema de cada bloque.
    fundamentador = FundamentacionNormativaAgent(model=request.modelo)
    problemas_resp: list[ProblemaInforme] = []
    total_problemas = sum(len(b.problemas) for b in informe.bloques)
    logger.info(
        "[API /investigacion/conclusion] Fundamentando %d problema(s) en %d bloque(s)",
        total_problemas, len(informe.bloques),
    )
    idx = 0
    for bloque in informe.bloques:
        for problema in bloque.problemas:
            idx += 1
            logger.info(
                "[API /investigacion/conclusion] Problema %d/%d | medio=%s | tipo=%s",
                idx, total_problemas, bloque.medio_id, problema.tipo,
            )
            fundamentador.fundamentar(problema, clasificacion, contexto=informe.motivo or "")
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

    # Conclusión: veredicto FUNDADO/INFUNDADO por regla sobre los objetivos.
    veredicto = ConclusionAgent(model=request.modelo).concluir_y_asignar(informe)

    texto = construir_texto_informe(informe)

    tiempo = time.perf_counter() - t_inicio
    logger.info(
        "[API /investigacion/conclusion] COMPLETADO | veredicto=%s | bloques=%d | problemas=%d | tiempo=%.2fs",
        veredicto, len(informe.bloques), len(problemas_resp), tiempo,
    )
    logger.info("=" * 60)

    return InformeResponse(
        codreclamo=request.codreclamo,
        informe=texto,
        problemas=problemas_resp,
        tiempo=tiempo,
    )


@router.post("/investigacion/informe/preview", response_model=InformePreviewResponse)
async def informe_preview(request: InformePreviewRequest) -> InformePreviewResponse:
    """
    Devuelve el texto del informe con los bloques registrados hasta el momento
    (metadatos + resumen de cada medio ya analizado), sin fundamentación
    normativa ni conclusión. No llama al LLM: es solo el renderizado del estado
    actual del informe en el store. Sirve para mostrar un borrador en vivo
    mientras se van analizando los medios probatorios (p.ej. con "Investigar
    todo"), y para obtener la cabecera del informe apenas se busca el reclamo.
    """
    informe = informe_store.obtener(request.codreclamo)
    if informe is None:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}. Busque el reclamo primero.",
        )
    texto = construir_texto_informe(informe)
    return InformePreviewResponse(codreclamo=request.codreclamo, informe=texto)


@router.post("/investigacion/conclusion/stream")
async def generar_conclusion_stream(request: InformeRequest) -> StreamingResponse:
    """Concluye el informe en streaming (NDJSON). Por cada problema de cada medio
    emite dos eventos a medida que se producen:

    1. ``articulos``: los artículos SUNASS recuperados para ese problema.
    2. ``fundamentacion``: la inferencia del LLM (acción, responsable, base legal).

    Al final emite ``informe`` con el texto en lenguaje natural ya armado.
    """

    async def generador():
        t_inicio = time.perf_counter()
        logger.info("=" * 60)
        logger.info("[API /investigacion/conclusion/stream] codreclamo=%s", request.codreclamo)

        informe = informe_store.obtener(request.codreclamo)
        if informe is None:
            yield json.dumps({
                "evento": "error",
                "error": (
                    f"No hay un informe en curso para el reclamo {request.codreclamo}. "
                    "Busque el reclamo y analice al menos un medio antes de concluirlo."
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
                        fundamentador.fundamentar_articulos, problema, informe.motivo or "",
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
                        problema, articulos, clasificacion, informe.motivo or "",
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

            # --- Conclusión: veredicto FUNDADO/INFUNDADO ----------------------
            conclusionador = ConclusionAgent(model=request.modelo)
            veredicto = await run_in_threadpool(conclusionador.concluir_y_asignar, informe)
            yield json.dumps({
                "evento": "conclusion",
                "veredicto": veredicto,
                "conclusion": informe.conclusion,
            }, ensure_ascii=False) + "\n"

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
                "[API /investigacion/conclusion/stream] COMPLETADO | bloques=%d | problemas=%d | tiempo=%.2fs",
                len(informe.bloques), len(problemas_resp), tiempo,
            )
            logger.info("=" * 60)
        except Exception as e:  # noqa: BLE001
            logger.exception("[API /investigacion/conclusion/stream] ERROR")
            yield json.dumps({"evento": "error", "error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(generador(), media_type="application/x-ndjson")


@router.post("/conciliacion/propuesta", response_model=ConciliacionResponse)
async def generar_propuesta(request: ConciliacionRequest) -> ConciliacionResponse:
    """
    Genera la propuesta de conciliación a partir de la CONCLUSIÓN del informe de
    atención (leída del store), no del texto completo del informe.
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

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /conciliacion/propuesta] COMPLETADO | veredicto=%s | tiempo=%.2fs",
                informe.veredicto, tiempo)
    logger.info("=" * 60)

    return ConciliacionResponse(
        codreclamo=request.codreclamo,
        propuesta=resultado["propuesta"],
        tiempo=tiempo,
    )


@router.post("/resolucion", response_model=ResolucionResponse)
async def generar_resolucion(request: ResolucionRequest) -> ResolucionResponse:
    """
    Genera la resolución final del reclamo. El tipo (FUNDADO/INFUNDADO) NO lo
    decide el LLM: se toma del veredicto ya fijado en el informe (paso de
    conclusión); el LLM solo redacta los considerandos que lo fundamentan,
    usando los datos del reclamo y la conclusión de la investigación (ambos
    leídos del informe en el store) más la propuesta de conciliación de la
    empresa y la postura del cliente.
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

    tiempo = time.perf_counter() - t_inicio

    logger.info("[API /resolucion] COMPLETADO | tipo=%s | tiempo=%.2fs", resultado["tipo"], tiempo)
    logger.info("=" * 60)

    return ResolucionResponse(
        codreclamo=request.codreclamo,
        tipo=resultado["tipo"],
        resolucion=resultado["resolucion"],
        tiempo=tiempo,
    )


