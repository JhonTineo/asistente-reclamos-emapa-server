import time
import logging
from langchain_core.messages import SystemMessage
from app.src.application.adapters.llm import get_llm, log_uso_llm

logger = logging.getLogger("agent.conciliador")


class ConciliadorAgent:
    """Redacta la propuesta de conciliación a partir de la CONCLUSIÓN del informe
    de atención (que ya describe los hallazgos frente a los objetivos y declara
    FUNDADO/INFUNDADO). El agente no re-analiza el informe completo: solo reformula
    la conclusión como propuesta formal de la empresa y cierra con la declaración
    del veredicto. El veredicto lo fija el informe; el LLM no puede cambiarlo."""

    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)

    def generar_propuesta(
        self,
        codreclamo: str,
        veredicto: str,
        conclusion: str,
        numero_informe: str,
    ) -> dict:
        t_inicio = time.perf_counter()

        logger.info("=" * 60)
        logger.info("[CONCILIADOR] INICIO | codreclamo=%s | veredicto=%s", codreclamo, veredicto)

        prompt = self._construir_prompt(veredicto, conclusion, numero_informe)
        logger.debug("[PROMPT conciliador][SYSTEM]\n%s", prompt)
        logger.info("[CONCILIADOR] Invocando LLM...")

        response = self.llm.invoke([SystemMessage(content=prompt)])
        log_uso_llm(logger, "conciliador", response)
        contenido = response.content.strip() if response.content else ""

        t_duracion = time.perf_counter() - t_inicio
        logger.info("[CONCILIADOR] COMPLETADO | %d caracteres | tiempo=%.2fs", len(contenido), t_duracion)
        logger.info("=" * 60)

        return {
            "propuesta": contenido,
            "tiempo": t_duracion,
        }

    @staticmethod
    def _construir_prompt(veredicto: str, conclusion: str, numero_informe: str) -> str:
        veredicto = (veredicto or "").strip().upper() or "INFUNDADO"
        cierre = (
            f"Por tanto, la empresa propone declarar {veredicto} el presente "
            f"reclamo, en base al Informe de Atención N° {numero_informe}."
        )
        return (
            "Eres un agente de conciliación de EMAPA. Redactas la PROPUESTA DE "
            "CONCILIACIÓN que la empresa presenta al usuario, a partir de la "
            "conclusión del informe de atención.\n\n"
            f"El veredicto ya fue determinado y NO puedes cambiarlo: {veredicto}.\n\n"
            "La propuesta debe:\n"
            "1. Explicar de forma clara y formal, en uno o dos párrafos, los "
            "hallazgos de la investigación respecto a lo reclamado, tomándolos de "
            "la conclusión (no inventes cifras ni artículos que no estén en ella).\n"
            f"2. Cerrar EXACTAMENTE con esta oración: \"{cierre}\"\n\n"
            "=== CONCLUSIÓN DEL INFORME DE ATENCIÓN ===\n"
            f"{conclusion}\n\n"
            "Responde ÚNICAMENTE con la propuesta redactada, sin encabezados ni "
            "comentarios adicionales."
        )
