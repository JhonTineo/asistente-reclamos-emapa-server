import time
import asyncio
import logging
import json
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from app.src.infrastructure.api_rest.deps import usar_token_emapa, asegurar_token_emapa, usar_config_llm
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
    BuscarReclamoRequest,
    BuscarReclamoResponse,
    ObjetivosRequest,
    ObjetivosResponse,
    ObjetivoInvestigacionSchema,
    MediosDisponiblesRequest,
    MediosDisponiblesResponse,
    MedioDisponible,
    ActualizarResumenRequest,
    ActualizarResumenResponse,
    ActualizarConclusionRequest,
    ActualizarConclusionResponse,
)
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
    obtener_record_facturacion,
    obtener_saldo_actual,
)


logger = logging.getLogger("api.investigacion")

# Prefix único: todos los endpoints de este router son parte del proceso de
# Investigación (medios probatorios + objetivos + conclusión). Propuesta de
# conciliación y resolución viven en sus propios routers (conciliacion.py,
# resolucion.py) aunque dependan de la conclusión generada aquí.
#
# Tags secundarios "interactivo" / "automatizacion" distinguen los endpoints
# con streaming (pensados para que el frontend muestre progreso en vivo al
# usuario) de sus equivalentes sin streaming (pensados para flujos
# automatizados donde nadie está mirando y solo importa el resultado final).
router = APIRouter(
    prefix="/investigacion",
    tags=["investigacion"],
    dependencies=[Depends(usar_token_emapa), Depends(usar_config_llm)],
)


def _enfoque_para_medio(informe, medio_id: str) -> str | None:
    """Reúne las preguntas de los objetivos de investigación asignados a este
    medio, para dirigir el énfasis del resumen del LLM. None si no hay objetivos
    para el medio (p.ej. aún no se generaron)."""
    if not informe or not informe.objetivos:
        return None
    preguntas = [o.descripcion for o in informe.objetivos
                 if o.medio == medio_id and o.descripcion]
    return " ".join(preguntas) or None


def _codigo_inspeccion_para_medio(informe, medio_id: str) -> str | None:
    """codinspeccion (nroinspeccion) del reclamo, solo para inspeccion_interna/
    externa; None para los demás medios (no lo usan)."""
    if not informe or not informe.datos_reclamo:
        return None
    if medio_id == "inspeccion_interna":
        return informe.datos_reclamo.codinspeccion_interna
    if medio_id == "inspeccion_externa":
        return informe.datos_reclamo.codinspeccion_externa
    return None


def _medios_determinantes(informe) -> set[str]:
    """Medios de los objetivos determinantes (los que deciden el veredicto). La
    fundamentación normativa se limita a estos: fundamentar hallazgos de medios
    no determinantes es trabajo perdido (la conclusión solo usa los
    determinantes) y añade ruido de artículos irrelevantes."""
    if not informe or not informe.objetivos:
        return set()
    return {o.medio for o in informe.objetivos if o.determinante and o.medio}


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

    # Fecha de recepción del reclamo: cada medio calcula su propia ventana
    # calendario a partir de (meses, fecha_ref) — ver ventana_utils.py; no hace
    # falta leer ni pasar la ventana de otro medio analizado antes.
    informe = informe_store.obtener(request.codreclamo)
    fecha_ref = informe.datos_reclamo.fecha_recepcion if informe and informe.datos_reclamo else None
    enfoque = _enfoque_para_medio(informe, medio_id)
    codinspeccion = _codigo_inspeccion_para_medio(informe, medio_id)

    # Sin código de inspección vinculado al reclamo (ya se guardó None al
    # buscarlo): NO se consulta a EMAPA (el endpoint filtra por nroinspeccion,
    # no por cliente — pasarle el suministro traería la inspección de otro
    # cliente). Se corta aquí con un error claro, sin registrar bloque, para
    # que el frontend alerte y no agregue este punto al informe.
    if medio_id in ("inspeccion_interna", "inspeccion_externa") and not codinspeccion:
        etiqueta = "interna" if medio_id == "inspeccion_interna" else "externa"
        logger.warning(
            "[API /investigacion/%s] Sin código de inspección %s vinculado al reclamo %s",
            medio_id, etiqueta, request.codreclamo,
        )
        logger.info("=" * 60)
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró inspección {etiqueta} para este reclamo.",
        )

    analista = AnalistaMedioAgent(model=request.modelo)
    bloque, ventana = analista.analizar(
        medio_id=medio_id,
        medio_nombre=medio_nombre,
        codsuc=request.codsuc,
        codcliente=request.codcliente,
        clasificacion=request.clasificacion,
        meses=request.meses,
        fecha_ref=fecha_ref,
        enfoque=enfoque,
        codinspeccion=codinspeccion,
    )

    informe = informe_store.registrar_bloque(
        codreclamo=request.codreclamo,
        bloque=bloque,
        suministro=request.codcliente,
        clasificacion=request.clasificacion,
    )
    # Persiste la ventana devuelta (informativa para el frontend; la calcula
    # tarjeta_lectura, pero es la misma para todos los medios de serie temporal).
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
    1. ``preprocesamiento``: datos y problemas por reglas .
    2. ``resumen``: interpretación del LLM en lenguaje natural .
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
        # Fecha de recepción del reclamo: cada medio calcula su propia ventana
        # calendario a partir de (meses, fecha_ref) — ver ventana_utils.py; ya no
        # depende de que otro medio la haya calculado antes.
        informe = informe_store.obtener(request.codreclamo)
        fecha_ref = informe.datos_reclamo.fecha_recepcion if informe and informe.datos_reclamo else None
        enfoque = _enfoque_para_medio(informe, medio_id)
        codinspeccion = _codigo_inspeccion_para_medio(informe, medio_id)

        # Sin código de inspección vinculado al reclamo (ya se guardó None al
        # buscarlo): NO se consulta a EMAPA. Se emite el error y se corta ANTES
        # de la Fase 1, sin registrar bloque, para que el frontend alerte y no
        # agregue este punto al informe.
        if medio_id in ("inspeccion_interna", "inspeccion_externa") and not codinspeccion:
            etiqueta = "interna" if medio_id == "inspeccion_interna" else "externa"
            logger.warning(
                "[API /investigacion/%s/stream] Sin código de inspección %s vinculado al reclamo %s",
                medio_id, etiqueta, request.codreclamo,
            )
            yield json.dumps({
                "evento": "error",
                "medio_id": medio_id,
                "error": f"No se encontró inspección {etiqueta} para este reclamo.",
            }, ensure_ascii=False) + "\n"
            return

        analista = AnalistaMedioAgent(model=request.modelo)
        try:
            # --- Fase 1: preprocesamiento  ---------------------------
            datos, problemas, ventana = await run_in_threadpool(
                analista.preprocesar,
                medio_id, medio_nombre, request.codsuc, request.codcliente,
                request.meses, fecha_ref, codinspeccion,
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

            # --- Fase 2: interpretación LLM  --------------------------
            resumen = await run_in_threadpool(
                analista.interpretar,
                medio_id, medio_nombre, datos, problemas, request.clasificacion, enfoque,
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
            # Persiste la ventana devuelta (informativa para el frontend; la
            # calcula tarjeta_lectura, pero es la misma para todos los medios).
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


@router.post("/inspeccion-externa/stream", tags=["interactivo"])
async def inspeccion_externa_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return _stream_analisis_medio(request, "inspeccion_externa", "Inspección Externa")


@router.post("/inspeccion-interna/stream", tags=["interactivo"])
async def inspeccion_interna_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return _stream_analisis_medio(request, "inspeccion_interna", "Inspección Interna")


@router.post("/tarjeta-lectura/stream", tags=["interactivo"])
async def tarjeta_lectura_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return _stream_analisis_medio(request, "tarjeta_lectura", "Tarjeta de Lecturas")


@router.post("/corte-reapertura/stream", tags=["interactivo"])
async def corte_reapertura_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return _stream_analisis_medio(request, "corte_reapertura", "Cortes y Reaperturas")


@router.post("/record-facturacion/stream", tags=["interactivo"])
async def record_facturacion_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return _stream_analisis_medio(request, "record_facturacion", "Record de Facturación")


@router.post("/saldo-detalle/stream", tags=["interactivo"])
async def saldo_detalle_stream(request: BuscarReclamoRequest) -> StreamingResponse:
    """Versión streaming: emite preprocesamiento y luego el resumen del LLM.
    Pensada para uso interactivo (el frontend muestra progreso en vivo)."""
    return _stream_analisis_medio(request, "saldo_detalle", "Saldo Detalle")


@router.post("/inspeccion-externa", response_model=ResumenMedio, tags=["automatizacion"])
async def inspeccion_externa(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección externa y registra su bloque en el informe.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await _analizar_medio_y_registrar(request, "inspeccion_externa", "Inspección Externa")


@router.post("/inspeccion-interna", response_model=ResumenMedio, tags=["automatizacion"])
async def inspeccion_interna(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la inspección interna y registra su bloque en el informe.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await _analizar_medio_y_registrar(request, "inspeccion_interna", "Inspección Interna")


@router.post("/tarjeta-lectura", response_model=ResumenMedio, tags=["automatizacion"])
async def tarjeta_lectura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza la tarjeta de lecturas (micromedición) y registra su bloque.
    Sin streaming: espera el resultado completo. Pensada para flujos
    automatizados sin usuario mirando la pantalla."""
    return await _analizar_medio_y_registrar(request, "tarjeta_lectura", "Tarjeta de Lecturas")


@router.post("/corte-reapertura", response_model=ResumenMedio, tags=["automatizacion"])
async def corte_reapertura(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza los cortes/reaperturas y registra su bloque en el informe.
    Requiere que se haya analizado antes la tarjeta de lecturas (fija la
    ventana). Sin streaming: pensada para flujos automatizados."""
    return await _analizar_medio_y_registrar(request, "corte_reapertura", "Cortes y Reaperturas")


@router.post("/record-facturacion", response_model=ResumenMedio, tags=["automatizacion"])
async def record_facturacion(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza el record de facturación (cómo se facturó cada mes: por lectura o
    por promedio) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana de meses). Sin streaming: pensada para
    flujos automatizados."""
    return await _analizar_medio_y_registrar(request, "record_facturacion", "Record de Facturación")


@router.post("/saldo-detalle", response_model=ResumenMedio, tags=["automatizacion"])
async def saldo_detalle(request: BuscarReclamoRequest) -> ResumenMedio:
    """Analiza el saldo-detalle (pagos por mes: cobro indebido, mora y meses
    pendientes) y registra su bloque. Requiere que se haya analizado antes la
    tarjeta de lecturas (fija la ventana de meses). Sin streaming: pensada
    para flujos automatizados."""
    return await _analizar_medio_y_registrar(request, "saldo_detalle", "Saldo Detalle")


@router.patch("/{medio}/resumen", response_model=ActualizarResumenResponse)
async def actualizar_resumen(medio: str, request: ActualizarResumenRequest) -> ActualizarResumenResponse:
    """
    Edita a mano el resumen (texto narrativo) de un medio ya analizado, sin
    tocar los problemas detectados ni invocar al LLM. No borra la conclusión,
    propuesta o resolución ya generadas: el usuario decide si las edita él
    mismo o las vuelve a generar con este resumen actualizado. Devuelve el
    informe re-renderizado para refrescar la sección de informe de atención.
    """
    medio_id = medio.replace("-", "_")
    actualizado = informe_store.actualizar_resumen(request.codreclamo, medio_id, request.resumen)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un bloque analizado para el medio '{medio}' en el reclamo {request.codreclamo}.",
        )
    informe = informe_store.obtener(request.codreclamo)
    return ActualizarResumenResponse(
        codreclamo=request.codreclamo,
        medio_id=medio_id,
        resumen=request.resumen,
        informe_texto=construir_texto_informe(informe),
    )


# Medios cuya disponibilidad se puede verificar (función EMAPA por medio).
# El orden define el orden de análisis en el frontend. inspeccion_interna/
# externa NO están aquí: su disponibilidad no se verifica llamando a EMAPA con
# codcliente (el endpoint filtra por nroinspeccion, no por cliente), sino
# comprobando si el reclamo tiene un codinspeccion vinculado (ver
# `_verificar_inspecciones` en medios_disponibles).
_MEDIOS_VERIFICABLES = {
    "tarjeta_lectura": lambda r: obtener_tarjeta_lectura(r.codsuc, r.codcliente),
    "record_facturacion": lambda r: obtener_record_facturacion(r.codsuc, r.codcliente, r.anio),
    "corte_reapertura": lambda r: obtener_corte_reapertura(r.codsuc, r.codcliente),
    "saldo_detalle": lambda r: obtener_saldo_actual(r.codsuc, r.codcliente),
    "saldo_actual": lambda r: obtener_saldo_actual(r.codsuc, r.codcliente),
}


def _tiene_datos(respuesta: dict) -> bool:
    """True si la respuesta de EMAPA trae datos utilizables (no 404/parcial ni vacío)."""
    if not isinstance(respuesta, dict) or respuesta.get("_partial"):
        return False
    return bool(respuesta.get("data"))


@router.post("/objetivos", response_model=ObjetivosResponse)
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


@router.post("/medios-disponibles", response_model=MediosDisponiblesResponse)
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

    def _verificar_inspecciones() -> list[MedioDisponible]:
        """inspeccion_interna/externa están disponibles si el reclamo tiene un
        codinspeccion vinculado (extraído al buscarlo); no se llama a EMAPA
        aquí (ver _codigo_inspeccion_para_medio)."""
        informe = informe_store.obtener(request.codreclamo)
        return [
            MedioDisponible(
                medio_id=medio_id,
                disponible=bool(_codigo_inspeccion_para_medio(informe, medio_id)),
            )
            for medio_id in ("inspeccion_externa", "inspeccion_interna")
        ]

    medios = [
        *await asyncio.gather(
            *(_verificar(mid, fn) for mid, fn in _MEDIOS_VERIFICABLES.items())
        ),
        *_verificar_inspecciones(),
    ]

    tiempo = time.perf_counter() - t_inicio
    disponibles = sum(1 for m in medios if m.disponible)
    logger.info(
        "[API /investigacion/medios-disponibles] COMPLETADO | disponibles=%d/%d | tiempo=%.2fs",
        disponibles, len(medios), tiempo,
    )
    return MediosDisponiblesResponse(codreclamo=request.codreclamo, medios=list(medios), tiempo=tiempo)


@router.post("/conclusion", response_model=InformeResponse, tags=["automatizacion"])
async def generar_conclusion(request: InformeRequest) -> InformeResponse:
    """
    Concluye el informe de atención: recupera el informe (con los bloques ya
    llenados por cada medio), fundamenta normativamente cada problema
    detectado y devuelve el texto final en lenguaje natural. Sin streaming:
    pensada para flujos automatizados.
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

    # Fase 4: fundamentación normativa. Solo se fundamentan los hallazgos de los
    # medios DETERMINANTES (los que deciden el veredicto); los demás se incluyen
    # sin fundamentar. Si no hay determinantes, se fundamenta todo (respaldo).
    fundamentador = FundamentacionNormativaAgent(model=request.modelo)
    problemas_resp: list[ProblemaInforme] = []
    medios_det = _medios_determinantes(informe)
    total_a_fundamentar = sum(
        len(b.problemas) for b in informe.bloques if not medios_det or b.medio_id in medios_det
    )
    logger.info(
        "[API /investigacion/conclusion] Fundamentando %d problema(s) de medios "
        "determinantes %s (de %d bloque(s))",
        total_a_fundamentar, sorted(medios_det) or "TODOS", len(informe.bloques),
    )
    idx = 0
    for bloque in informe.bloques:
        fundamentar_medio = not medios_det or bloque.medio_id in medios_det
        for problema in bloque.problemas:
            if fundamentar_medio:
                idx += 1
                logger.info(
                    "[API /investigacion/conclusion] Problema %d/%d | medio=%s | tipo=%s",
                    idx, total_a_fundamentar, bloque.medio_id, problema.tipo,
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


@router.patch("/conclusion", response_model=ActualizarConclusionResponse)
async def actualizar_conclusion(request: ActualizarConclusionRequest) -> ActualizarConclusionResponse:
    """
    Edita a mano el párrafo de conclusión, sin tocar el veredicto ni invocar
    al LLM. Devuelve el informe re-renderizado para refrescar la sección de
    informe de atención con el nuevo texto.
    """
    actualizado = informe_store.actualizar_conclusion(request.codreclamo, request.conclusion)
    if not actualizado:
        raise HTTPException(
            status_code=404,
            detail=f"No hay un informe en curso para el reclamo {request.codreclamo}.",
        )
    informe = informe_store.obtener(request.codreclamo)
    return ActualizarConclusionResponse(
        codreclamo=request.codreclamo,
        conclusion=request.conclusion,
        informe_texto=construir_texto_informe(informe),
    )


@router.post("/informe/preview", response_model=InformePreviewResponse)
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


@router.post("/conclusion/stream", tags=["interactivo"])
async def generar_conclusion_stream(request: InformeRequest) -> StreamingResponse:
    """Concluye el informe en streaming (NDJSON). Por cada problema de cada medio
    emite dos eventos a medida que se producen:

    1. ``articulos``: los artículos SUNASS recuperados para ese problema.
    2. ``fundamentacion``: la inferencia del LLM (acción, responsable, base legal).

    Al final emite ``informe`` con el texto en lenguaje natural ya armado.
    Pensada para uso interactivo (el frontend muestra progreso en vivo).
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

        # Solo se fundamentan los hallazgos de los medios DETERMINANTES (los que
        # deciden el veredicto); los demás se incluyen sin fundamentar. Si no hay
        # determinantes, se fundamenta todo (respaldo).
        medios_det = _medios_determinantes(informe)
        total = sum(
            len(b.problemas) for b in informe.bloques if not medios_det or b.medio_id in medios_det
        )
        yield json.dumps({"evento": "inicio", "total_problemas": total}, ensure_ascii=False) + "\n"

        fundamentador = FundamentacionNormativaAgent(model=request.modelo)
        problemas_resp: list[ProblemaInforme] = []
        indice = 0

        try:
            for bloque in informe.bloques:
                fundamentar_medio = not medios_det or bloque.medio_id in medios_det
                for problema in bloque.problemas:
                    if fundamentar_medio:
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
                        indice += 1

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
