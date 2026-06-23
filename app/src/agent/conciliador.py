import json
import time
import logging
from pathlib import Path
from langchain_core.messages import SystemMessage
from core.llm import get_llm

logger = logging.getLogger("agent.conciliador")

SOLUCIONES_PATH = Path(__file__).parent.parent / "storage" / "soluciones.json"


def _cargar_soluciones() -> dict:
    return json.loads(SOLUCIONES_PATH.read_text(encoding="utf-8"))


class ConciliadorAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)

    def generar_propuesta(self, codreclamo: str, clasificacion: str, informe_atencion: str) -> dict:
        t_inicio = time.perf_counter()

        logger.info("=" * 60)
        logger.info("[CONCILIADOR] INICIO - Generando propuesta")
        logger.info("[CONCILIADOR] codreclamo=%s | clasificacion=%s", codreclamo, clasificacion)
        logger.info("[CONCILIADOR] Longitud informe: %d caracteres", len(informe_atencion))

        soluciones = _cargar_soluciones()
        soluciones_texto = self._formatear_soluciones(soluciones)

        prompt = self._construir_prompt(codreclamo, clasificacion, informe_atencion, soluciones_texto)

        logger.info("[CONCILIADOR] Invocando LLM...")
        t_llm_inicio = time.perf_counter()

        response = self.llm.invoke([SystemMessage(content=prompt)])
        contenido = response.content if response.content else ""

        t_llm = time.perf_counter() - t_llm_inicio
        t_duracion = time.perf_counter() - t_inicio

        logger.info("[CONCILIADOR] LLM completado (%.2fs)", t_llm)
        logger.info("[CONCILIADOR] Propuesta generada (%d caracteres)", len(contenido))
        logger.info("[CONCILIADOR] COMPLETADO | tiempo=%.2fs", t_duracion)
        logger.info("=" * 60)

        return {
            "propuesta": contenido,
            "tiempo": t_duracion,
        }

    def _formatear_soluciones(self, soluciones: dict) -> str:
        lineas = ["=== SOLUCIONES DISPONIBLES ===\n"]

        lineas.append("RESPONSABILIDAD DE LA EMPRESA:")
        for sol in soluciones.get("responsabilidad_empresa", []):
            lineas.append(f"  - Si {sol['causa']}: {sol['accion']}")

        lineas.append("\nRESPONSABILIDAD DEL CLIENTE:")
        for sol in soluciones.get("responsabilidad_cliente", []):
            lineas.append(f"  - Si {sol['causa']}: {sol['accion']}")

        lineas.append("\nRESPONSABILIDAD COMPARTIDA:")
        for sol in soluciones.get("compartido", []):
            lineas.append(f"  - Si {sol['causa']}: Empresa: {sol['accion_empresa']}, Cliente: {sol['accion_cliente']}")

        return "\n".join(lineas)

    def _construir_prompt(self, codreclamo: str, clasificacion: str, informe: str, soluciones: str) -> str:
        return (
            f"Eres un agente especialista en conciliación de reclamos de EMAPA.\n\n"
            f"Tu tarea es analizar el informe de atención y generar una propuesta de conciliación.\n\n"
            f"Código de Reclamo: {codreclamo}\n"
            f"Clasificación: {clasificacion}\n\n"
            f"{soluciones}\n\n"
            f"=== INFORME DE ATENCIÓN ===\n"
            f"{informe}\n\n"
            f"=== FORMATO DE LA PROPUESTA ===\n"
            f"Según el informe de atención al reclamo se obtuvieron los siguientes hallazgos:\n"
            f"- (Hallazgo 1 con responsabilidad identificada)\n"
            f"- (Hallazgo 2 con responsabilidad identificada)\n"
            f"- (etc.)\n\n"
            f"Por tanto se propone las siguientes acciones:\n"
            f"- La empresa debe: (acción si es responsabilidad de la empresa)\n"
            f"- El cliente debe: (acción si es responsabilidad del cliente)\n"
            f"- La empresa debe: / El cliente debe: (acción si es compartida)\n\n"
            f"=== INSTRUCCIONES ===\n"
            f"1. Lee el informe línea por línea e identifica cada hallazgo significativo\n"
            f"2. Clasifica cada hallazgo como:\n"
            f"   - RESPONSABILIDAD DE LA EMPRESA: Si fue causado por error, omisión o negligencia de la empresa\n"
            f"   - RESPONSABILIDAD DEL CLIENTE: Si fue causado por acciones, instalaciones o negligencia del cliente\n"
            f"   - RESPONSABILIDAD COMPARTIDA: Si ambos tienen parte de la responsabilidad\n"
            f"3. Para cada hallazgo, propón la acción correspondiente usando las soluciones disponibles\n"
            f"4. Usa un lenguaje profesional y claro\n"
            f"5. Sé justo y objetivo en la distribución de responsabilidades\n\n"
            f"Responde ÚNICAMENTE con la propuesta en el formato especificado."
        )
