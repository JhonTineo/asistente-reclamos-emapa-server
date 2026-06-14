import json
import re
import time
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from app.core.llm import get_llm
from app.schemas.investigacion import TareaInforme, Hallazgo
from app.tools.registry import ToolRegistry
from app.tools.mapper import obtener_tool_para_medio
from app.agent.base import Agent

logger = logging.getLogger("agent.investigador")


def _extraer_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta: {texto[:200]}")
    return json.loads(match.group())


class InvestigadorAgent(Agent):
    role = "investigador"

    def run(self, input_data: dict) -> dict:
        tarea = input_data["tarea"]
        suministro_id = input_data["suministro_id"]
        detalle = input_data["detalle"]
        modelo = input_data.get("modelo")

        return _ejecutar_tarea_sincrono(tarea, suministro_id, detalle, modelo)


def _ejecutar_tarea_sincrono(
    tarea: TareaInforme,
    suministro_id: str,
    detalle: str,
    modelo: str | None,
) -> Hallazgo:
    t_inicio = time.perf_counter()

    logger.info("[INVESTIGADOR] Ejecutando tarea | id=%s | nombre=%s | medios=%d",
                tarea.id, tarea.nombre, len(tarea.medios_requeridos))

    datos_medios = _obtener_datos_medios(tarea.medios_requeridos, suministro_id)

    llm = get_llm(model=modelo)

    prompt_sistema = tarea.prompt
    prompt_datos = _construir_prompt_datos(tarea.nombre, datos_medios, detalle, suministro_id)

    logger.info("[INVESTIGADOR] Invocando LLM para análisis | id=%s", tarea.id)
    t_llm_inicio = time.perf_counter()

    response = llm.invoke([
        SystemMessage(content=prompt_sistema),
        HumanMessage(content=prompt_datos),
    ])

    t_llm = time.perf_counter() - t_llm_inicio
    t_ejecucion = time.perf_counter() - t_inicio

    try:
        data = _extraer_json(response.content)
        hallazgos = data.get("hallazgos", [])
        conclusion = data.get("conclusion", "")
    except Exception as e:
        logger.warning("[INVESTIGADOR] Error parseando JSON de tarea %s: %s", tarea.id, str(e))
        hallazgos = [f"Error al procesar: {str(e)}"]
        conclusion = "No se pudo generar conclusión"

    logger.info("[INVESTIGADOR] Tarea completada | id=%s | hallazgos=%d | tiempo=%.2fs (llm=%.2fs)",
                tarea.id, len(hallazgos), t_ejecucion, t_llm)

    return Hallazgo(
        informe_id=tarea.id,
        informe_nombre=tarea.nombre,
        medios_utilizados=tarea.medios_requeridos,
        hallazgos=hallazgos,
        conclusion=conclusion,
    )


def _obtener_datos_medios(medios_requeridos: list[str], suministro_id: str) -> dict[str, str]:
    datos = {}
    for medio in medios_requeridos:
        tool_name = obtener_tool_para_medio(medio)
        if not tool_name:
            datos[medio] = f"Tool no encontrada para: {medio}"
            continue

        tool = ToolRegistry.get_tool(tool_name)
        if not tool:
            datos[medio] = f"Tool '{tool_name}' no registrada"
            continue

        logger.info("[INVESTIGADOR] Ejecutando tool=%s | medio=%s", tool_name, medio[:50])
        result = tool.execute(suministro_id=suministro_id)

        if result.success:
            datos[medio] = result.data or "Sin datos"
        else:
            datos[medio] = f"Error: {result.error}"

    return datos


def _construir_prompt_datos(
    informe_nombre: str,
    datos_medios: dict[str, str],
    detalle: str,
    suministro_id: str,
) -> str:
    medios_texto = []
    for medio, datos in datos_medios.items():
        medios_texto.append(f"=== {medio} ===\n{datos}\n")

    return (
        f"=== DATOS OBTENIDOS DE MEDIOS PROBATORIOS ===\n\n"
        f"Suministro ID: {suministro_id}\n"
        f"Detalle del reclamo: {detalle}\n\n"
        f"{chr(10).join(medios_texto)}\n\n"
        "Analiza los datos anteriores y genera los hallazgos y conclusión para el informe."
    )
