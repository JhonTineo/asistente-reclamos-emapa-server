"""Servicio de aplicación para el análisis de medios probatorios: arma el
enfoque/código de inspección a partir de los objetivos y del reclamo, analiza
un medio y registra su bloque en el informe. Usado tanto por los endpoints
sync (investigacion.py) como por los de streaming (investigacion_stream.py).
"""

import asyncio
import time
import json
import logging

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.src.infrastructure.api_rest.deps import asegurar_token_emapa
from app.src.infrastructure.api_rest.schemas.investigacion import (
    BuscarReclamoRequest, ResumenMedio, ProblemaNormadoSchema, MedioDisponible,
)
from app.src.application.usecase.agents.analista_medio import AnalistaMedioAgent
from app.src.application.services.informe.informe_store import informe_store
from app.src.core.model.informe_atencion import BloqueMedio

logger = logging.getLogger("services.investigacion_service")


def enfoque_para_medio(informe, medio_id: str) -> str | None:
    """Reúne las preguntas de los objetivos de investigación asignados a este
    medio, para dirigir el énfasis del resumen del LLM. None si no hay objetivos
    para el medio (p.ej. aún no se generaron)."""
    if not informe or not informe.objetivos:
        return None
    preguntas = [o.descripcion for o in informe.objetivos
                 if o.medio == medio_id and o.descripcion]
    return " ".join(preguntas) or None


def codigo_inspeccion_para_medio(informe, medio_id: str) -> str | None:
    """codinspeccion (nroinspeccion) del reclamo, solo para inspeccion_interna/
    externa; None para los demás medios (no lo usan)."""
    if not informe or not informe.datos_reclamo:
        return None
    if medio_id == "inspeccion_interna":
        return informe.datos_reclamo.codinspeccion_interna
    if medio_id == "inspeccion_externa":
        return informe.datos_reclamo.codinspeccion_externa
    return None


def medios_determinantes(informe) -> set[str]:
    """Medios de los objetivos determinantes (los que deciden el veredicto). La
    fundamentación normativa se limita a estos: fundamentar hallazgos de medios
    no determinantes es trabajo perdido (la conclusión solo usa los
    determinantes) y añade ruido de artículos irrelevantes."""
    if not informe or not informe.objetivos:
        return set()
    return {o.medio for o in informe.objetivos if o.determinante and o.medio}


async def analizar_medio_y_registrar(
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
    enfoque = enfoque_para_medio(informe, medio_id)
    codinspeccion = codigo_inspeccion_para_medio(informe, medio_id)

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


async def _analizar_un_medio_en_threadpool(
    request: BuscarReclamoRequest,
    medio_id: str,
    medio_nombre: str,
) -> ResumenMedio:
    """Como ``analizar_medio_y_registrar``, pero corre la parte bloqueante
    (``analista.analizar``: HTTP a EMAPA + LLM) en un threadpool. Es lo que
    permite que ``analizar_medios_en_paralelo`` logre paralelismo REAL entre
    medios con ``asyncio.gather`` — sin el threadpool, cada medio bloquearía
    el event-loop por turno y el análisis seguiría siendo secuencial.

    Uso interno de ``analizar_medios_en_paralelo``: no se expone aparte."""
    t_inicio = time.perf_counter()

    informe = informe_store.obtener(request.codreclamo)
    fecha_ref = informe.datos_reclamo.fecha_recepcion if informe and informe.datos_reclamo else None
    enfoque = enfoque_para_medio(informe, medio_id)
    codinspeccion = codigo_inspeccion_para_medio(informe, medio_id)

    if medio_id in ("inspeccion_interna", "inspeccion_externa") and not codinspeccion:
        etiqueta = "interna" if medio_id == "inspeccion_interna" else "externa"
        raise HTTPException(
            status_code=404,
            detail=f"No se encontró inspección {etiqueta} para este reclamo.",
        )

    analista = AnalistaMedioAgent(model=request.modelo)
    bloque, ventana = await run_in_threadpool(
        analista.analizar,
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

    # Se ejecuta de vuelta en el event-loop (tras el await anterior), sin
    # ceder el control a otra corrutina en el medio: seguro contra carreras
    # aunque varios medios completen su threadpool casi al mismo tiempo.
    informe = informe_store.registrar_bloque(
        codreclamo=request.codreclamo,
        bloque=bloque,
        suministro=request.codcliente,
        clasificacion=request.clasificacion,
    )
    if ventana:
        informe.ventana_meses = ventana

    tiempo_total = time.perf_counter() - t_inicio
    logger.info(
        "[informe-atencion/%s] COMPLETADO | problemas=%d | tiempo=%.2fs",
        medio_id, len(bloque.problemas), tiempo_total,
    )

    return ResumenMedio(
        medio_id=bloque.medio_id,
        medio_nombre=bloque.medio_nombre,
        datos=bloque.entidad,
        resumen=bloque.resumen,
        problemas=[ProblemaNormadoSchema(**vars(p)) for p in bloque.problemas],
        tiempo=tiempo_total,
    )


async def analizar_medios_en_paralelo(
    request: BuscarReclamoRequest,
    medios: list[tuple[str, str]],
) -> tuple[list[str], list[MedioDisponible]]:
    """Analiza varios medios probatorios EN PARALELO (un threadpool por medio,
    orquestados con asyncio.gather) y registra cada bloque en el informe a
    medida que van completando. Pensada para el orquestador de un solo golpe
    (POST /reclamos/informe-atencion), donde nadie mira el progreso paso a
    paso; para el flujo interactivo con progreso en vivo se sigue usando
    ``analizar_medio_y_registrar`` / ``stream_analisis_medio`` (uno a la vez).

    Un medio sin datos/inspección o que falla por cualquier motivo se omite
    sin abortar el análisis de los demás.

    Devuelve (medios_analizados, medios_omitidos).
    """
    await asegurar_token_emapa(request.codreclamo)

    resultados = await asyncio.gather(
        *(
            _analizar_un_medio_en_threadpool(request, medio_id, medio_nombre)
            for medio_id, medio_nombre in medios
        ),
        return_exceptions=True,
    )

    medios_analizados: list[str] = []
    medios_omitidos: list[MedioDisponible] = []
    for (medio_id, _), resultado in zip(medios, resultados):
        if isinstance(resultado, HTTPException):
            logger.warning("[informe-atencion] medio %s omitido: %s", medio_id, resultado.detail)
            medios_omitidos.append(
                MedioDisponible(medio_id=medio_id, disponible=False, error=str(resultado.detail))
            )
        elif isinstance(resultado, BaseException):
            logger.error(
                "[informe-atencion] error analizando %s: %s", medio_id, resultado, exc_info=resultado
            )
            medios_omitidos.append(
                MedioDisponible(medio_id=medio_id, disponible=False, error=str(resultado))
            )
        else:
            medios_analizados.append(medio_id)

    return medios_analizados, medios_omitidos


def stream_analisis_medio(
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
        enfoque = enfoque_para_medio(informe, medio_id)
        codinspeccion = codigo_inspeccion_para_medio(informe, medio_id)

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
