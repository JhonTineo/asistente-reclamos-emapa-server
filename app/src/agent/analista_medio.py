import time
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from core.llm import get_llm

logger = logging.getLogger("agent.analista_medio")


CLUES_BUSQUEDA = {
    "Consumo medido": "buscar inconsistencias entre consumo facturado y consumo real del medidor, anomalías en lecturas, consumos fuera de rango normal",
    "Consumo promedio": "buscar el promedio aplicado, los meses utilizados para el cálculo, si fue válido aplicar promedio",
    "Asignación de consumo": "buscar criterios de asignación, número de unidades de uso asignadas, justificación",
    "Consumo no facturado": "buscar períodos no facturados, razones del omissions, consumo omitido",
    "Corte y reapertura": "buscar fechas de corte y reapertura, motivos, estado actual del servicio",
    "Pago": "buscar estado de pagos, recibos pendientes, promesas de pago, mora",
    "Inspección": "buscar resultado de inspección, estado del medidor, anomalías encontradas",
    "default": "buscar información relevante para el reclamo, anomalías, inconsistencies",
}


class AnalistaMedioAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)

    def analizar(self, medio_id: str, medio_nombre: str, datos: str, clasificacion: str) -> dict:
        t_inicio = time.perf_counter()

        clue = self._obtener_clue(clasificacion)
        prompt = self._construir_prompt(medio_nombre, datos, clue)

        response = self.llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"Analiza los datos y genera un resumen relevante para un reclamo de: {clasificacion}")
        ])

        t_duracion = time.perf_counter() - t_inicio
        contenido = response.content if response.content else ""

        logger.info("[ANALISTA_MEDIO] %s completado | tiempo=%.2fs", medio_nombre, t_duracion)

        return {
            "medio_id": medio_id,
            "medio_nombre": medio_nombre,
            "resumen": contenido,
            "tiempo": t_duracion,
        }

    def _obtener_clue(self, clasificacion: str) -> str:
        for key, clue in CLUES_BUSQUEDA.items():
            if key.lower() in clasificacion.lower():
                return clue
        return CLUES_BUSQUEDA["default"]

    def _construir_prompt(self, medio_nombre: str, datos: str, clue: str) -> str:
        return (
            f"Eres un analista especializado en medios probatorios de EMAPA.\n\n"
            f"Medio probatorio: {medio_nombre}\n\n"
            f"Información a buscar en este medio: {clue}\n\n"
            f"Datos obtenidos:\n{datos}\n\n"
            f"Tu tarea es:\n"
            f"1. Analizar los datos proporcionados\n"
            f"2. Buscar específicamente: {clue}\n"
            f"3. Generar un resumen corto (máximo 3-4 oraciones) con los hallazgos relevantes\n\n"
            f"Responde ÚNICAMENTE con el resumen, sin introducciones ni conclusiones.\n"
            f"Sé conciso y enfócate en lo importante para el reclamo."
        )
