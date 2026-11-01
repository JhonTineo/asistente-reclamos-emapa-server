import time
import logging
from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT

logger = logging.getLogger("agent.conciliador")


class ConciliadorAgent:
    """Redacta la propuesta de conciliación a partir de la CONCLUSIÓN del informe
    de atención (que ya describe los hallazgos frente a los objetivos y declara
    FUNDADO/INFUNDADO). El agente no re-analiza el informe completo: solo reformula
    la conclusión como propuesta formal de la empresa y cierra con la declaración
    del veredicto. El veredicto lo fija el informe; el LLM no puede cambiarlo."""

    def __init__(self, llm_router: LlmRouterService, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT

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

        response_text = self.llm_router.generar_texto(
            mensajes=[MensajeLLM(rol="system", contenido=prompt)],
            modelo_id=self.model_id
        )
        contenido = response_text.strip() if response_text else ""

        t_duracion = time.perf_counter() - t_inicio
        logger.info("[CONCILIADOR] COMPLETADO | %d caracteres | tiempo=%.2fs", len(contenido), t_duracion)
        logger.info("=" * 60)

        return {
            "propuesta": contenido,
            "tiempo": t_duracion,
        }

    @staticmethod
    def _construir_prompt(veredicto: str, conclusion: str, numero_informe: str) -> str:
        """El texto de la propuesta tiene el formato fijo de EMAPA (ver
        services/informe/formatos.py). Aquí la IA solo redacta el SUSTENTO: la
        frase que completa "AL HABERSE VERIFICADO QUE ...", tomada de la
        conclusión del informe de atención."""
        veredicto = (veredicto or "").strip().upper() or "INFUNDADO"
        ejemplo = (
            "EL CONSUMO FACTURADO SE AJUSTA A REGISTROS REALES CONFORME AL ANÁLISIS TÉCNICO EFECTUADO"
            if veredicto == "INFUNDADO" else
            "EL MEDIDOR REGISTRÓ UN CONSUMO ATÍPICO EN EL MES RECLAMADO, POR LO QUE CORRESPONDE "
            "REFACTURAR EL CONSUMO POR EL PROMEDIO HISTÓRICO"
        )
        return (
            "Eres un agente de conciliación de EMAPA. Redactas el SUSTENTO TÉCNICO de la "
            "propuesta de conciliación, a partir de la conclusión del informe de atención "
            f"N° {numero_informe}.\n\n"
            f"El veredicto ya fue determinado y NO puedes cambiarlo: {veredicto}.\n\n"
            "Escribe UNA sola frase, EN MAYÚSCULAS, que complete esta oración: "
            "\"AL HABERSE VERIFICADO QUE ...\". No repitas esas palabras iniciales; "
            "empieza directamente por lo verificado. Máximo 45 palabras.\n"
            "- Usa SOLO hechos de la conclusión (cifras, lecturas, inspección); no inventes "
            "datos ni cites artículos (los artículos se agregan aparte).\n"
            "- No menciones al usuario por su nombre ni declares el veredicto (también se "
            "agrega aparte).\n"
            f"Ejemplo de estilo: \"{ejemplo}\".\n\n"
            "=== CONCLUSIÓN DEL INFORME DE ATENCIÓN ===\n"
            f"{conclusion}\n\n"
            "Responde ÚNICAMENTE con la frase, sin comillas ni comentarios."
        )
