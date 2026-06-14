import json
import re
import time
import logging
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
from app.core.llm import get_llm
from app.schemas.reclamo import ClasificarReclamoResponse
from app.agent.base import Agent

logger = logging.getLogger("agent.clasificador")

ANEXO1_PATH = Path(__file__).parent.parent / "storage" / "anexo1_tipos_reclamos.md"

PROMPT_CLASIFICACION = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Eres un especialista en clasificación de reclamos de una empresa de servicios de agua "
            "potable y alcantarillado (EMAPA). Tu tarea es analizar el detalle del reclamo presentado "
            "por un cliente y clasificarlo según la documentación normativa del Anexo 1.\n\n"
            "Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional antes ni después. "
            "El JSON debe tener exactamente estos campos:\n"
            '  "clasificacion": el tipo de reclamo según el Anexo 1\n'
            '  "razonamiento": explicación breve de por qué se clasifica así\n\n'
            "Documentación normativa de referencia (Anexo 1 - Problemas de Alcance Particular):\n\n"
            "{anexo1}",
        ),
        (
            "user",
            "Clasifica el siguiente reclamo:\n\n"
            "ID de Reclamo: {reclamo_id}\n"
            "Suministro ID: {suministro_id}\n"
            "Detalle del reclamo: {detalle}",
        ),
    ]
)


def _cargar_anexo1() -> str:
    return ANEXO1_PATH.read_text(encoding="utf-8")


def _extraer_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta: {texto[:200]}")
    return json.loads(match.group())


class ClasificadorAgent(Agent):
    role = "clasificador"

    def run(self, input_data: dict) -> dict:
        reclamo_id = input_data["reclamo_id"]
        suministro_id = input_data["suministro_id"]
        detalle = input_data["detalle"]
        modelo = input_data.get("modelo")

        t_total_inicio = time.perf_counter()
        llm = get_llm(model=modelo)
        chain = PROMPT_CLASIFICACION | llm

        t_carga_inicio = time.perf_counter()
        anexo1 = _cargar_anexo1()
        t_carga = time.perf_counter() - t_carga_inicio

        prompt_input = {
            "anexo1": anexo1,
            "reclamo_id": reclamo_id,
            "suministro_id": suministro_id,
            "detalle": detalle,
        }

        modelo_usado = modelo or llm.model_name
        logger.info("[CLASIFICADOR] Prompt generado | reclamo=%s | suministro=%s | modelo=%s | tokens_prompt=~%d | carga_anexo=%.3fs",
                    reclamo_id, suministro_id, modelo_usado, len(anexo1) // 4, t_carga)

        logger.info("[CLASIFICADOR] Enviando prompt al modelo... | reclamo=%s", reclamo_id)
        t_llm_inicio = time.perf_counter()

        response = chain.invoke(prompt_input)

        t_llm = time.perf_counter() - t_llm_inicio
        t_chars = len(response.content) if response.content else 0

        logger.info("[CLASIFICADOR] Respuesta recibida | reclamo=%s | tiempo_llm=%.2fs | caracteres=%d",
                    reclamo_id, t_llm, t_chars)

        t_json_inicio = time.perf_counter()
        data = _extraer_json(response.content)
        t_json = time.perf_counter() - t_json_inicio

        resultado = ClasificarReclamoResponse(
            reclamo_id=reclamo_id,
            clasificacion=data["clasificacion"],
            razonamiento=data["razonamiento"],
        )

        t_total = time.perf_counter() - t_total_inicio
        t_overhead = t_total - t_llm
        logger.info("[CLASIFICADOR] Completado | reclamo=%s | total=%.2fs | llm=%.2fs | overhead=%.2fs (carga=%.3fs json=%.3fs)",
                    reclamo_id, t_total, t_llm, t_overhead, t_carga, t_json)

        return {
            "reclamo_id": resultado.reclamo_id,
            "clasificacion": resultado.clasificacion,
            "razonamiento": resultado.razonamiento,
        }


def clasificar_reclamo(reclamo_id: str, suministro_id: str, detalle: str, modelo: str | None = None) -> ClasificarReclamoResponse:
    agent = ClasificadorAgent(model=modelo)
    result = agent.run({
        "reclamo_id": reclamo_id,
        "suministro_id": suministro_id,
        "detalle": detalle,
        "modelo": modelo,
    })
    return ClasificarReclamoResponse(
        reclamo_id=result["reclamo_id"],
        clasificacion=result["clasificacion"],
        razonamiento=result["razonamiento"],
    )
