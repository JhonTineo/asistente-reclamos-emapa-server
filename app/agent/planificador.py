import json
import re
import time
import logging
from langchain_core.prompts import ChatPromptTemplate
from app.core.llm import get_llm
from app.schemas.investigacion import (
    TareaInforme,
    PlanificarInvestigacionResponse,
)
from app.skills.investigacion import obtener_tareas_informe
from app.agent.base import Agent

logger = logging.getLogger("agent.planificador")

PROMPT_DESCRIPCION = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Eres un especialista en planificación de investigaciones de reclamos de EMAPA. "
            "Genera una descripción breve (2-3 oraciones) del plan de investigación para el "
            "reclamo dado, mencionando la clasificación y las tareas principales a realizar.\n\n"
            "Responde ÚNICAMENTE con un objeto JSON válido:\n"
            '  "descripcion_planificacion": descripción breve del plan de investigación\n',
        ),
        (
            "user",
            "Reclamo ID: {reclamo_id}\n"
            "Suministro ID: {suministro_id}\n"
            "Clasificación: {clasificacion}\n"
            "Detalle: {detalle}\n"
            "Tareas a realizar: {tareas_resumen}",
        ),
    ]
)


def _extraer_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta: {texto[:200]}")
    return json.loads(match.group())


class PlanificadorAgent(Agent):
    role = "planificador"

    def run(self, input_data: dict) -> dict:
        reclamo_id = input_data["reclamo_id"]
        suministro_id = input_data["suministro_id"]
        clasificacion = input_data["clasificacion"]
        detalle = input_data["detalle"]
        modelo = input_data.get("modelo")

        t_total_inicio = time.perf_counter()

        t_skill_inicio = time.perf_counter()
        tareas = obtener_tareas_informe(clasificacion, suministro_id, detalle)
        t_skill = time.perf_counter() - t_skill_inicio

        tareas_resumen = "\n".join(
            f"- {t['id']}: {t['nombre']} (medios: {len(t['medios_requeridos'])})"
            for t in tareas
        )

        logger.info("[PLANIFICADOR] Tareas generadas | reclamo=%s | suministro=%s | clasificacion=%s | tareas=%d | skill=%.3fs",
                    reclamo_id, suministro_id, clasificacion, len(tareas), t_skill)

        llm = get_llm(model=modelo)
        chain = PROMPT_DESCRIPCION | llm

        modelo_usado = modelo or llm.model_name
        logger.info("[PLANIFICADOR] Generando descripción del plan... | reclamo=%s | modelo=%s",
                    reclamo_id, modelo_usado)

        t_llm_inicio = time.perf_counter()
        response = chain.invoke({
            "reclamo_id": reclamo_id,
            "suministro_id": suministro_id,
            "clasificacion": clasificacion,
            "detalle": detalle,
            "tareas_resumen": tareas_resumen,
        })
        t_llm = time.perf_counter() - t_llm_inicio

        t_json_inicio = time.perf_counter()
        data = _extraer_json(response.content)
        t_json = time.perf_counter() - t_json_inicio

        resultado = PlanificarInvestigacionResponse(
            reclamo_id=reclamo_id,
            clasificacion=clasificacion,
            descripcion_planificacion=data["descripcion_planificacion"],
            tareas=[
                TareaInforme(
                    id=t["id"],
                    nombre=t["nombre"],
                    medios_requeridos=t["medios_requeridos"],
                    prompt=t["prompt"],
                    entrada=t["entrada"],
                    salida=t["salida"],
                )
                for t in tareas
            ],
        )

        t_total = time.perf_counter() - t_total_inicio
        t_overhead = t_total - t_llm - t_skill
        logger.info("[PLANIFICADOR] Completado | reclamo=%s | total=%.2fs | skill=%.3fs | llm=%.2fs | overhead=%.2fs",
                    reclamo_id, t_total, t_skill, t_llm, t_overhead)

        return {
            "reclamo_id": resultado.reclamo_id,
            "clasificacion": resultado.clasificacion,
            "descripcion_planificacion": resultado.descripcion_planificacion,
            "tareas": resultado.tareas,
        }


def planificar_investigacion(
    suministro_id: str,
    reclamo_id: str,
    clasificacion: str,
    detalle: str,
    modelo: str | None = None,
) -> PlanificarInvestigacionResponse:
    agent = PlanificadorAgent(model=modelo)
    result = agent.run({
        "reclamo_id": reclamo_id,
        "suministro_id": suministro_id,
        "clasificacion": clasificacion,
        "detalle": detalle,
        "modelo": modelo,
    })
    return PlanificarInvestigacionResponse(
        reclamo_id=result["reclamo_id"],
        clasificacion=result["clasificacion"],
        descripcion_planificacion=result["descripcion_planificacion"],
        tareas=result["tareas"],
    )
