import json
import time
import logging
from dataclasses import asdict
from langchain_core.messages import HumanMessage, SystemMessage
from app.src.application.adapters.llm import get_llm
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.application.services.pre_proces.pre_inspeccion_interna_service import PreInspeccionInternaService
from app.src.application.services.pre_proces.pre_targeta_lecturas_service import PreTargetaLecturasService
from app.src.application.services.pre_proces.pre_corte_reapertura_service import PreCorteReaperturaService
from app.src.core.model.investigacion import HallazgoInvestigacion

logger = logging.getLogger("agent.analista_medio")


class AnalistaMedioAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)
        self.pre_ext_service = PreInspeccionExternaService()
        self.pre_int_service = PreInspeccionInternaService()
        self.pre_tarj_service = PreTargetaLecturasService()
        self.pre_corte_service = PreCorteReaperturaService()

    def analizar(self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str, clasificacion: str) -> HallazgoInvestigacion:
        t_inicio = time.perf_counter()
        logger.info("Iniciando análisis para medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)

        entidad = self._dispatch_preprocesamiento(medio_id, codsuc, codcliente)
        t2 = time.perf_counter()
        logger.info("Preprocesamiento completado | medio=%s | tiempo=%.2fs", medio_nombre, t2 - t_inicio)

        datos = asdict(entidad)
        datos_texto = json.dumps(datos, ensure_ascii=False, indent=2)
        prompt = self._construir_prompt(medio_nombre, datos_texto)
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
            datos=datos,
            analisis=contenido,
            tiempo=tiempo,
        )

    def _dispatch_preprocesamiento(self, medio_id: str, codsuc: str, codcliente: str):
        """Devuelve la entidad de dominio preprocesada según el medio."""
        if medio_id == "inspeccion_externa":
            return self.pre_ext_service.preprocesar_inspeccion_externa(codsuc, codcliente)["inspeccion"]
        elif medio_id == "inspeccion_interna":
            return self.pre_int_service.preprocesar_inspeccion_interna(codsuc, codcliente)["inspeccion"]
        elif medio_id == "tarjeta_lectura":
            return self.pre_tarj_service.preprocesar_targeta_lecturas(codsuc, codcliente)["targeta"]
        elif medio_id == "corte_reapertura":
            return self.pre_corte_service.preprocesar_corte_reapertura(codsuc, codcliente)["corte"]
        else:
            raise ValueError(f"Medio no soportado para preprocesamiento: {medio_id}")

    def _construir_prompt(self, medio_nombre: str, datos: str) -> str:
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
