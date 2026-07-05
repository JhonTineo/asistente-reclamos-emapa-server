import time
import logging
from app.src.core.service.tools.emapa_api import obtener_inspeccion_externa
from app.src.application.services.rag.retriever import Retriever

logger = logging.getLogger("services.pre_inspeccion_externa_service")

class PreInspeccionExternaService:

    def __init__(self):
        self.retriever = Retriever()

    CAMPOS_RELEVANTES_INSPECCION_EXTERNA = {
        "cab": [
            "nroinspeccion",
            "fechainspeccion",
            "funcionamed",
            "fugas",
            "tipofugas",
            "observacionmed",
            "estadocaja",
            "observacionsum",
            "estconexion",
            "nomresponsable",
            "atipico",
        ]
    }

    FORMATO_RESPUESTA_INSPECCION_EXTERNA = (
        "La inspección externa realizada por el inspector {nomresponsable} con fecha "
        "{fechainspeccion} con número de inspección {nroinspeccion} reveló lo siguiente: "
        "{observaciones}."
    )

    INDICADORES_INSPECCION_EXTERNA = {
        "fugas": {
            "0": "No se detectaron fugas de agua.",
            "1": "Se detectaron fugas de agua.",
        },
        "tipofugas": {
            "000": "[No especificado]",
            "001": "No Hay",
            "002": "Fuga en la Caja de Registro con Fuga.",
            "003": "Fuga despues del Medidor.",
            "004": "Fuga antes del Medidor.",
        },
        "funcionamed": {
            "1": "El medidor funciona correctamente.",
            "0": "El medidor no funciona correctamente.",
        },
        "estadocaja": {
            "001": "La caja del medidor está en buen estado.",
            "002": "La caja del medidor está en mal estado.",
        },
        "estconexion": {
            "001": "La conexión del medidor está en buen estado.",
            "002": "La conexión del medidor está en mal estado.",
        },
        "atipico": {
            "1": "Se detectaron condiciones atípicas en la inspección.",
            "0": "No se detectaron condiciones atípicas en la inspección.",
        }
    }
  
    def preprocesar_inspeccion_externa(self, codsuc: str, codcliente: str) -> dict:
        t1 = time.time()
        json_raw = obtener_inspeccion_externa(codsuc, codcliente)
        t2 = time.time()
        logger.info("[PRE_INSPECCION_EXTERNA] Datos obtenidos de EMAPA en %.2f segundos", t2 - t1)
        datos_limpios = self._filtrar_campos_inspeccion_externa(json_raw)
        t3 = time.time()
        logger.info("[PRE_INSPECCION_EXTERNA] Datos filtrados en %.2f segundos", t3 - t2)
        observaciones = self._extraer_observaciones_inspeccion_externa(datos_limpios)
        t4 = time.time()
        logger.info("[PRE_INSPECCION_EXTERNA] Observaciones extraídas en %.2f segundos", t4 - t3)
        articulos_sunass = []
        if observaciones:
            logger.info("[PRE_INSPECCION_EXTERNA] Buscando artículos SUNASS para las observaciones extraídas")
            articulos_sunass = self._buscar_articulos_sunass(observaciones)
            t5 = time.time()
            logger.info("[PRE_INSPECCION_EXTERNA] Artículos SUNASS encontrados en %.2f segundos", t5 - t4)
        t_final = time.time()
        logger.info("[PRE_INSPECCION_EXTERNA] Preprocesamiento completo en %.2f segundos", t_final - t1)
        return {
            "datos": datos_limpios,
            "articulos_sunass": articulos_sunass,
            "formato_respuesta": self.FORMATO_RESPUESTA_INSPECCION_EXTERNA,
        }

    def _filtrar_campos_inspeccion_externa(self, json_raw: dict) -> dict:
        data = json_raw.get("data", {})
        cab_raw = data.get("cab", {})
        cab_filtrado = {
            k: v for k, v in cab_raw.items()
            if k in self.CAMPOS_RELEVANTES_INSPECCION_EXTERNA["cab"]
        }
        cab_interpretado = self._interpretar_valores_cab(cab_filtrado)
        return {
            "cab": cab_interpretado
        }

    def _interpretar_valores_cab(self, cab: dict) -> dict:
        cab_interpretado = dict(cab)
        for campo, valores in self.INDICADORES_INSPECCION_EXTERNA.items():
            if campo in cab_interpretado:
                valor_original = str(cab_interpretado[campo])
                cab_interpretado[campo] = valores.get(valor_original, valor_original)
        return cab_interpretado

    def _extraer_observaciones_inspeccion_externa(self, datos_limpios: dict) -> list[str]:
        cab = datos_limpios.get("cab", {})
        observaciones = []
        for campo, valor in cab.items():
            if "observacion" in campo and valor:
                observaciones.append(f"{campo}: {valor}")
        return observaciones
    
    def _buscar_articulos_sunass(self, observaciones: list[str], top_k: int = 2) -> list[dict]:
            try:
                resultados = self.retriever.retrieve(
                    query=" ".join(observaciones),
                    top_k=top_k,
                    collection_name="sunass_reglamento",
                )
                if resultados and resultados[0]["score"] > 0.5:
                    context = self.retriever.build_context("sunass_reglamento", resultados)
                    return [
                        {"articulo": r["payload"].get("article", ""),
                        "numeral": r["payload"].get("numeral", ""),
                        "texto": r["payload"].get("text", ""),
                        "score": r["score"]}
                        for r in resultados
                    ]
            except Exception as e:
                logger.warning("[ANALISTA_MEDIO] Error buscando artículos SUNASS: %s", str(e))
            return []


