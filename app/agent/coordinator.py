import time
import logging
import asyncio
from app.schemas.investigacion import (
    TareaInforme,
    Hallazgo,
)
from app.agent.clasificador import ClasificadorAgent
from app.agent.planificador import PlanificadorAgent
from app.agent.investigador import InvestigadorAgent
from app.agent.unificador import UnificadorAgent

logger = logging.getLogger("agent.coordinator")


async def ejecutar_investigacion_completa(
    suministro_id: str,
    detalle: str,
    modelo: str | None = None,
) -> dict:
    """
    Orchestrates the complete multi-agent investigation flow:
    1. Clasificador → classification
    2. Planificador → plan + tasks
    3. Investigador (parallel) → findings per task
    4. Unificador → final explanation
    """
    t_total_inicio = time.perf_counter()
    reclamo_id = f"rec-{suministro_id}-{int(time.time())}"

    logger.info("[COORDINATOR] Iniciando investigación completa | suministro=%s | tiempo=%.3fs",
                suministro_id, time.perf_counter() - t_total_inicio)

    logger.info("[COORDINATOR] FASE 1: Clasificación | suministro=%s", suministro_id)
    t_clasif_inicio = time.perf_counter()
    clasificador = ClasificadorAgent(model=modelo)
    result_clasif = clasificador.run({
        "reclamo_id": reclamo_id,
        "suministro_id": suministro_id,
        "detalle": detalle,
        "modelo": modelo,
    })
    t_clasif = time.perf_counter() - t_clasif_inicio
    clasificacion = result_clasif["clasificacion"]
    logger.info("[COORDINATOR] Clasificación completada | clasificacion=%s | tiempo=%.2fs",
                clasificacion, t_clasif)

    logger.info("[COORDINATOR] FASE 2: Planificación | suministro=%s", suministro_id)
    t_plan_inicio = time.perf_counter()
    planificador = PlanificadorAgent(model=modelo)
    result_plan = planificador.run({
        "reclamo_id": reclamo_id,
        "suministro_id": suministro_id,
        "clasificacion": clasificacion,
        "detalle": detalle,
        "modelo": modelo,
    })
    t_plan = time.perf_counter() - t_plan_inicio
    tareas = result_plan["tareas"]
    descripcion_plan = result_plan["descripcion_planificacion"]
    logger.info("[COORDINATOR] Planificación completada | tareas=%d | tiempo=%.2fs",
                len(tareas), t_plan)

    logger.info("[COORDINATOR] FASE 3: Investigación paralela | suministro=%s | tareas=%d",
                suministro_id, len(tareas))
    t_inv_inicio = time.perf_counter()

    investigador = InvestigadorAgent(model=modelo)
    tareas_con_datos = [
        {
            "tarea": tarea,
            "suministro_id": suministro_id,
            "detalle": detalle,
            "modelo": modelo,
        }
        for tarea in tareas
    ]
    resultados_tareas: list[Hallazgo] = await asyncio.gather(*[
        asyncio.to_thread(investigador.run, td) for td in tareas_con_datos
    ])
    t_inv = time.perf_counter() - t_inv_inicio
    logger.info("[COORDINATOR] Investigación completada | hallazgos=%d | tiempo=%.2fs",
                len(resultados_tareas), t_inv)

    logger.info("[COORDINATOR] FASE 4: Unificación | suministro=%s", suministro_id)
    t_unif_inicio = time.perf_counter()
    unificador = UnificadorAgent(model=modelo)
    result_unif = unificador.run({
        "reclamo_id": reclamo_id,
        "suministro_id": suministro_id,
        "clasificacion": clasificacion,
        "detalle": detalle,
        "resultados_tareas": list(resultados_tareas),
        "modelo": modelo,
    })
    t_unif = time.perf_counter() - t_unif_inicio
    logger.info("[COORDINATOR] Unificación completada | procede=%s | tiempo=%.2fs",
                result_unif["procede"], t_unif)

    t_total = time.perf_counter() - t_total_inicio
    logger.info("[COORDINATOR] Investigación completa | suministro=%s | total=%.2fs | "
                "clasif=%.2fs | plan=%.2fs | inv=%.2fs | unif=%.2fs",
                suministro_id, t_total, t_clasif, t_plan, t_inv, t_unif)

    return {
        "reclamo_id": reclamo_id,
        "suministro_id": suministro_id,
        "clasificacion": clasificacion,
        "descripcion_plan": descripcion_plan,
        "tareas": tareas,
        "resultados_tareas": list(resultados_tareas),
        "explicacion_unificada": result_unif["explicacion_unificada"],
        "procede": result_unif["procede"],
        "acciones": result_unif["acciones"],
    }
