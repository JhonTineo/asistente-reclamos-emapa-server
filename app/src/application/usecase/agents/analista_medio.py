import json
import time
import logging
from dataclasses import asdict
from langchain_core.messages import HumanMessage, SystemMessage
from app.src.application.adapters.llm import get_llm
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.application.services.pre_proces.pre_inspeccion_interna_service import PreInspeccionInternaService
from app.src.core.model.investigacion import HallazgoInvestigacion

logger = logging.getLogger("agent.analista_medio")


class AnalistaMedioAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)
        self.pre_ext_service = PreInspeccionExternaService()
        self.pre_int_service = PreInspeccionInternaService()

    def analizar(self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str, clasificacion: str) -> HallazgoInvestigacion:
        t_inicio = time.perf_counter()
        logger.info("Iniciando análisis para medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)

        resultado_preproceso = self._dispatch_preprocesamiento(medio_id, codsuc, codcliente)
        inspeccion = resultado_preproceso["inspeccion"]
        t2 = time.perf_counter()
        logger.info("Preprocesamiento completado | medio=%s | tiempo=%.2fs", medio_nombre, t2 - t_inicio)

        prompt = self._construir_prompt(medio_nombre, inspeccion)
        logger.info("Prompt construido | medio=%s", medio_nombre)
        logger.info("Prompt:\n%s", prompt)
        logger.info("Consultando al modelo")
        response = self.llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"Analiza los datos y genera un resumen relevante para un reclamo de: {clasificacion}")
        ])
        contenido = response.content if response.content else ""
        tiempo = time.perf_counter() - t_inicio
        logger.info("Resumen completado | medio=%s | tiempo=%.2fs", medio_nombre, tiempo)

        return HallazgoInvestigacion(
            medio_id=medio_id,
            medio_nombre=medio_nombre,
            analisis=contenido,
            tiempo=tiempo,
        )

    def _dispatch_preprocesamiento(self, medio_id: str, codsuc: str, codcliente: str) -> dict:
        if medio_id == "inspeccion_externa":
            return self.pre_ext_service.preprocesar_inspeccion_externa(codsuc, codcliente)
        elif medio_id == "inspeccion_interna":
            return self.pre_int_service.preprocesar_inspeccion_interna(codsuc, codcliente)
        else:
            raise ValueError(f"Medio no soportado para preprocesamiento: {medio_id}")

    def _construir_prompt(self, medio_nombre: str, inspeccion) -> str:
        datos = json.dumps(asdict(inspeccion), ensure_ascii=False, indent=2)
        partes_prompt = [
            "Eres un analista especializado en medios probatorios de EMAPA.",
            "",
            f"Medio probatorio: {medio_nombre}",
            "",
            "Datos obtenidos:",
            datos,
            "",
            "Tu tarea es:",
            "1. Analizar los datos proporcionados",
            "2. Generar un resumen corto (máximo 3-4 oraciones) con los hallazgos relevantes",
            "",
            "Responde ÚNICAMENTE con el resumen, sin introducciones, recomendaciones ni conclusiones.",
            "Sé conciso y enfócate en lo importante para el reclamo.",
        ]
        return "\n".join(partes_prompt)
