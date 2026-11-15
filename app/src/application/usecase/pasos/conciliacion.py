import time
import logging
from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT

logger = logging.getLogger("paso.conciliacion")


class PasoConciliacion:
    """Redacta la propuesta de conciliación a partir de la CONCLUSIÓN del informe
    de atención (que ya describe los hallazgos frente a los objetivos y declara
    FUNDADO/INFUNDADO). El paso no re-analiza el informe completo: solo reformula
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

        instrucciones, entrada = self._construir_prompt(veredicto, conclusion, numero_informe)
        logger.info("[CONCILIADOR] Invocando LLM...")

        response_text = constructor_contexto.llamar(
            "conciliacion", self.llm_router, self.model_id,
            entrada=entrada, instrucciones=instrucciones, codreclamo=codreclamo,
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
    def _construir_prompt(veredicto: str, conclusion: str, numero_informe: str) -> tuple[str, str]:
        """Devuelve (instrucciones del caso, entrada). Lo fijo de la propuesta
        está en skills/pasos/conciliacion.md."""
        veredicto = (veredicto or "").strip().upper() or "INFUNDADO"
        cierre = (
            f"Por tanto, la empresa propone declarar {veredicto} el presente "
            f"reclamo, en base al Informe de Atención N° {numero_informe}."
        )
        instrucciones = (
            f"El veredicto ya fue determinado y NO puedes cambiarlo: {veredicto}.\n"
            f"Oración de cierre (cópiala EXACTAMENTE al final): \"{cierre}\""
        )
        entrada = f"=== CONCLUSIÓN DEL INFORME DE ATENCIÓN ===\n{conclusion}"
        return instrucciones, entrada
