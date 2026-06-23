import time
import logging
from langchain_core.messages import SystemMessage
from core.llm import get_llm

logger = logging.getLogger("agent.unificador")


class UnificadorAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)

    def generar_informe(self, codreclamo: str, clasificacion: str, detalle: str, resumenes: list[dict]) -> dict:
        t_inicio = time.perf_counter()

        logger.info("=" * 60)
        logger.info("[FASE 2] INICIO - Generacion de Informe")
        logger.info("[FASE 2] codreclamo=%s | clasificacion=%s", codreclamo, clasificacion)
        logger.info("[FASE 2] Detalle: %s", detalle[:100] + "..." if len(detalle) > 100 else detalle)
        logger.info("[FASE 2] Resumenes recibidos: %d", len(resumenes))
        logger.info("-" * 40)

        for i, r in enumerate(resumenes, 1):
            logger.info("[FASE 2] Resumen %d: %s", i, r["medio_nombre"])
            logger.info("[FASE 2]   %s", (r["resumen"][:80] + "...") if len(r["resumen"]) > 80 else r["resumen"])

        logger.info("-" * 40)
        logger.info("[FASE 2] Construyendo prompt para LLM...")

        prompt = self._construir_prompt(codreclamo, clasificacion, detalle, resumenes)

        logger.info("[FASE 2] Invocando LLM (modelo=%s)...", self.model or "default")
        t_llm_inicio = time.perf_counter()

        response = self.llm.invoke([SystemMessage(content=prompt)])

        t_llm = time.perf_counter() - t_llm_inicio
        contenido = response.content if response.content else ""

        t_duracion = time.perf_counter() - t_inicio

        logger.info("[FASE 2] LLM completado (%.2fs)", t_llm)
        logger.info("[FASE 2] Informe generado (%d caracteres)", len(contenido))
        logger.info("[FASE 2] COMPLETADA | tiempo_total=%.2fs", t_duracion)
        logger.info("=" * 60)

        return {
            "informe": contenido,
            "tiempo": t_duracion,
        }

    def _construir_prompt(self, codreclamo: str, clasificacion: str, detalle: str, resumenes: list[dict]) -> str:
        resumenes_texto = "\n\n".join([
            f"### {r['medio_nombre']}\n{r['resumen']}"
            for r in resumenes
        ])

        return (
            f"Eres un especialista en analisis de reclamos de EMAPA.\n\n"
            f"Genera un informe detallado y profesional para el siguiente reclamo:\n\n"
            f"Codigo de Reclamo: {codreclamo}\n"
            f"Clasificacion: {clasificacion}\n"
            f"Detalle del Reclamo: {detalle}\n\n"
            f"=== RESUMENES DE ANALISIS DE MEDIOS PROBATORIOS ===\n"
            f"{resumenes_texto}\n\n"
            f"=== FORMATO DEL INFORME ===\n"
            f"El informe debe incluir:\n"
            f"1. RESUMEN EJECUTIVO: Breve explicacion del problema identificado (2-3 oraciones)\n"
            f"2. ANTECEDENTES: Contexto del reclamo y lo reportado por el cliente\n"
            f"3. ANALISIS POR MEDIO PROBATORIO: Descripcion de lo encontrado en cada medio\n"
            f"4. HALLAZGOS: Lista de problemas o anomalias identificadas\n"
            f"5. CONCLUSION: Evaluacion tecnica del reclamo\n"
            f"6. RECOMENDACION: Acciones a seguir o solucion propuesta\n\n"
            f"Responde UNICAMENTE con el informe en el formato especificado.\n"
            f"Se profesional, objetivo y basa tus conclusiones en los datos."
        )
