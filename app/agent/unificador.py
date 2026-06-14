import json
import re
import time
import logging
from langchain_core.messages import SystemMessage
from app.core.llm import get_llm
from app.schemas.investigacion import Hallazgo
from app.skills.investigacion import generar_prompt_unificacion
from app.agent.base import Agent

logger = logging.getLogger("agent.unificador")


def _extraer_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta: {texto[:200]}")
    return json.loads(match.group())


class UnificadorAgent(Agent):
    role = "unificador"

    def run(self, input_data: dict) -> dict:
        reclamo_id = input_data["reclamo_id"]
        suministro_id = input_data["suministro_id"]
        clasificacion = input_data["clasificacion"]
        detalle = input_data["detalle"]
        resultados_tareas = input_data["resultados_tareas"]
        modelo = input_data.get("modelo")

        return _unificar_hallazgos_sincrono(
            reclamo_id, suministro_id, clasificacion, detalle, resultados_tareas, modelo
        )


def _unificar_hallazgos_sincrono(
    reclamo_id: str,
    suministro_id: str,
    clasificacion: str,
    detalle: str,
    resultados_tareas: list[Hallazgo],
    modelo: str | None,
) -> dict:
    t_inicio = time.perf_counter()

    logger.info("[UNIFICADOR] Iniciando unificación | reclamo=%s | informes=%d",
                reclamo_id, len(resultados_tareas))

    prompt_base = generar_prompt_unificacion(reclamo_id, suministro_id, clasificacion, detalle)

    prompt_informes = _construir_prompt_informes(resultados_tareas)

    prompt_completo = (
        f"{prompt_base}\n\n"
        f"=== INFORMES GENERADOS ===\n"
        f"{prompt_informes}\n\n"
        "Responde con el JSON final."
    )

    llm = get_llm(model=modelo)

    logger.info("[UNIFICADOR] Invocando LLM para unificación | reclamo=%s", reclamo_id)
    t_llm_inicio = time.perf_counter()

    response = llm.invoke([SystemMessage(content=prompt_completo)])

    t_llm = time.perf_counter() - t_llm_inicio

    try:
        data_unif = _extraer_json(response.content)
        explicacion_unificada = data_unif.get("explicacion_unificada", "")
        procede = data_unif.get("procede", "parcialmente")
        acciones = data_unif.get("acciones", [])
    except Exception as e:
        logger.warning("[UNIFICADOR] Error parseando unificación: %s", str(e))
        explicacion_unificada = "Error al generar explicación unificada"
        procede = "parcialmente"
        acciones = []

    t_total = time.perf_counter() - t_inicio
    logger.info("[UNIFICADOR] Unificación completada | reclamo=%s | procede=%s | tiempo=%.2fs (llm=%.2fs)",
                reclamo_id, procede, t_total, t_llm)

    return {
        "explicacion_unificada": explicacion_unificada,
        "procede": procede,
        "acciones": acciones,
    }


def _construir_prompt_informes(resultados_tareas: list[Hallazgo]) -> str:
    informes_texto = "\n\n".join(
        f"=== {h.informe_nombre} ===\n"
        f"Medios analizados: {', '.join(h.medios_utilizados)}\n"
        f"Hallazgos: {'; '.join(h.hallazgos)}\n"
        f"Conclusión: {h.conclusion}"
        for h in resultados_tareas
    )
    return informes_texto
