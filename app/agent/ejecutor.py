import json
import re
import time
import logging
import asyncio
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.llm import get_llm
from app.schemas.investigacion import (
    TareaInforme,
    Hallazgo,
    ResultadoInvestigacion,
)
from app.skills.investigacion import generar_prompt_unificacion

logger = logging.getLogger("agent.ejecutor")


def _extraer_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta: {texto[:200]}")
    return json.loads(match.group())


async def _ejecutar_tarea(tarea: TareaInforme, detalle: str, modelo: str | None) -> Hallazgo:
    """Ejecuta una tarea de informe (obtener medios, analizar, devolver hallazgos)."""
    t_inicio = time.perf_counter()

    llm = get_llm(model=modelo)

    logger.info("[EJECUTOR] Ejecutando tarea | id=%s | nombre=%s", tarea.id, tarea.nombre)

    mensajes = [
        SystemMessage(content=tarea.prompt),
        HumanMessage(content=f"Ejecuta la tarea para el reclamo con detalle: {detalle}"),
    ]

    response = await llm.ainvoke(mensajes)
    t_ejecucion = time.perf_counter() - t_inicio

    try:
        data = _extraer_json(response.content)
        hallazgos = data.get("hallazgos", [])
        conclusion = data.get("conclusion", "")
    except Exception as e:
        logger.warning("[EJECUTOR] Error parseando JSON de tarea %s: %s", tarea.id, str(e))
        hallazgos = [f"Error al procesar: {str(e)}"]
        conclusion = "No se pudo generar conclusión"

    logger.info("[EJECUTOR] Tarea completada | id=%s | hallazgos=%d | tiempo=%.2fs",
                tarea.id, len(hallazgos), t_ejecucion)

    return Hallazgo(
        informe_id=tarea.id,
        informe_nombre=tarea.nombre,
        medios_utilizados=tarea.medios_requeridos,
        hallazgos=hallazgos,
        conclusion=conclusion,
    )


def _construir_prompt_unificacion(
    reclamo_id: str,
    clasificacion: str,
    detalle: str,
    resultados_tareas: list[Hallazgo],
) -> str:
    """Construye el prompt completo para el agente unificador."""
    prompt_base = generar_prompt_unificacion(reclamo_id, clasificacion, detalle)

    informes_texto = "\n\n".join(
        f"=== {h.informe_nombre} ===\n"
        f"Medios analizados: {', '.join(h.medios_utilizados)}\n"
        f"Hallazgos: {'; '.join(h.hallazgos)}\n"
        f"Conclusión: {h.conclusion}"
        for h in resultados_tareas
    )

    return (
        f"{prompt_base}\n\n"
        f"=== INFORMES GENERADOS ===\n"
        f"{informes_texto}\n\n"
        "Responde con el JSON final."
    )


async def ejecutar_investigacion(
    reclamo_id: str,
    clasificacion: str,
    detalle: str,
    descripcion_planificacion: str,
    tareas: list[TareaInforme],
    modelo: str | None = None,
) -> ResultadoInvestigacion:
    """
    Ejecuta todas las tareas de informe en paralelo y luego unifica los resultados.
    """
    t_total_inicio = time.perf_counter()

    logger.info("[EJECUTOR] Iniciando ejecución | reclamo=%s | tareas=%d", reclamo_id, len(tareas))

    t_paralelo_inicio = time.perf_counter()
    resultados_tareas = await asyncio.gather(*[
        _ejecutar_tarea(tarea, detalle, modelo)
        for tarea in tareas
    ])
    t_paralelo = time.perf_counter() - t_paralelo_inicio

    logger.info("[EJECUTOR] Tareas completadas en paralelo | tiempo=%.2fs", t_paralelo)

    t_unificacion_inicio = time.perf_counter()
    prompt_unificacion = _construir_prompt_unificacion(
        reclamo_id, clasificacion, detalle, resultados_tareas
    )

    llm = get_llm(model=modelo)
    logger.info("[EJECUTOR] Ejecutando unificación | reclamo=%s", reclamo_id)

    response = await llm.ainvoke([
        SystemMessage(content=prompt_unificacion),
    ])

    t_unificacion = time.perf_counter() - t_unificacion_inicio

    try:
        data_unif = _extraer_json(response.content)
        explicacion_unificada = data_unif.get("explicacion_unificada", "")
    except Exception as e:
        logger.warning("[EJECUTOR] Error parseando unificación: %s", str(e))
        explicacion_unificada = "Error al generar explicación unificada"

    t_total = time.perf_counter() - t_total_inicio
    logger.info("[EJECUTOR] Ejecución completada | reclamo=%s | total=%.2fs | paralelo=%.2fs | unificacion=%.2fs",
                reclamo_id, t_total, t_paralelo, t_unificacion)

    return ResultadoInvestigacion(
        reclamo_id=reclamo_id,
        clasificacion=clasificacion,
        descripcion_planificacion=descripcion_planificacion,
        resultados_tareas=list(resultados_tareas),
        explicacion_unificada=explicacion_unificada,
    )