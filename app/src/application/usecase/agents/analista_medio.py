import time
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from app.src.application.adapters.llm import get_llm
from app.src.application.services.pre_proces.pre_inspeccion_externa_service import PreInspeccionExternaService
from app.src.application.services.pre_proces.pre_inspeccion_interna_service import PreInspeccionInternaService
from app.src.application.services.rag.retriever import Retriever

logger = logging.getLogger("agent.analista_medio")


class AnalistaMedioAgent:
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)
        self.retriever = Retriever()
        self.pre_ext_service = PreInspeccionExternaService()
        self.pre_int_service = PreInspeccionInternaService()

    def analizar(self, medio_id: str, medio_nombre: str, codsuc: str, codcliente: str, clasificacion: str) -> dict:
        t_inicio = time.perf_counter()
        logger.info("Iniciando análisis para medio: %s | codsuc=%s | codcliente=%s", medio_nombre, codsuc, codcliente)
        resultado_preproceso = self._dispatch_preprocesamiento(medio_id, codsuc, codcliente)
        t2 = time.perf_counter()
        logger.info("Preprocesamiento completado | medio=%s | tiempo=%.2fs", medio_nombre, t2 - t_inicio)
        formato_respuesta = resultado_preproceso.get("formato_respuesta")
        if formato_respuesta:
            cab = resultado_preproceso.get("datos", {}).get("cab", {})
            formato_respuesta = (
                formato_respuesta
                .replace("{nomresponsable}", str(cab.get("nomresponsable", "")))
                .replace("{fechainspeccion}", str(cab.get("fechainspeccion", "")))
                .replace("{nroinspeccion}", str(cab.get("nroinspeccion", "")))
            )
        prompt = self._construir_prompt(medio_nombre, resultado_preproceso, formato_respuesta)
        t3 = time.perf_counter()
        logger.info("Prompt construido | medio=%s | tiempo=%.2fs", medio_nombre, t3 - t2)
        logger.info("Prompt: %s", prompt)
        logger.info("Consultando al modelo")
        response = self.llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=f"Analiza los datos y genera un resumen relevante para un reclamo de: {clasificacion}")
        ])        
        t4 = time.perf_counter()
        logger.info("Respuesta del modelo recibida | medio=%s | tiempo=%.2fs", medio_nombre, t4 - t3)
        contenido = response.content if response.content else ""
        logger.info("Resumen completado | medio=%s | tiempo=%.2fs", medio_nombre, t4 - t_inicio)
        return {
            "medio_id": medio_id,
            "medio_nombre": medio_nombre,
            "resumen": contenido,
            "tiempo": t4 - t_inicio,
            "datos_preprocesados": resultado_preproceso.get("datos"),
            "articulos_sunass": resultado_preproceso.get("articulos_sunass", []),
            "formato_respuesta": formato_respuesta,
        }


    def _dispatch_preprocesamiento(self, medio_id: str, codsuc: str, codcliente: str) -> dict:
        if medio_id == "inspeccion_externa":
            return self.pre_ext_service.preprocesar_inspeccion_externa(codsuc, codcliente)
        elif medio_id == "inspeccion_interna":
            return self.pre_int_service.preprocesar_inspeccion_interna(codsuc, codcliente)
        else:
            raise ValueError(f"Medio no soportado para preprocesamiento: {medio_id}")

    def _construir_prompt(self, medio_nombre: str, resultado_preproceso: dict, formato_respuesta: str | None = None) -> str:
        import json
        datos = json.dumps(resultado_preproceso.get("datos", {}), ensure_ascii=False, indent=2)
        articulos = resultado_preproceso.get("articulos_sunass", [])
        partes_prompt = [
            f"Eres un analista especializado en medios probatorios de EMAPA.",
            f"",
            f"Medio probatorio: {medio_nombre}",
            f"",
            f"Datos obtenidos:",
            f"{datos}",
        ]
        if formato_respuesta:
            partes_prompt.append(f"")
            partes_prompt.append(f"Agrega las observaciones a este formato:")
            partes_prompt.append(f"{formato_respuesta}")
            partes_prompt.append(f"")
        if articulos:
            partes_prompt.append(f"")
            partes_prompt.append(f"Artículos normativos aplicables a las observaciones encontradas:")
            for i, art in enumerate(articulos, 1):
                partes_prompt.append(f"{i}. Artículo {art.get('articulo','')} {art.get('numeral','')}: {art.get('texto','')}")
        partes_prompt.extend([
            f"",
            f"Tu tarea es:",
            f"1. Analizar los datos proporcionados",
            f"2. Solo mensiona los articulos si alguna observación lo incumple",
            f"3. Generar un resumen corto (máximo 3-4 oraciones) con los hallazgos relevantes",
            f"",
            f"Responde ÚNICAMENTE con el resumen, sin introducciones, recomendaciones ni conclusiones.",
            f"Sé conciso y enfócate en lo importante para el reclamo.",
        ])

        return "\n".join(partes_prompt)




    

