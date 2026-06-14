import json
import time
import logging
from pathlib import Path
from langchain_core.tools import tool

ANEXO3_PATH = Path(__file__).parent.parent / "storage" / "anexo3_medios_probatorios.json"
INFORMES_PATH = Path(__file__).parent.parent / "storage" / "anexo3_informes.json"
logger = logging.getLogger("tools.investigacion")



@tool
def consultar_medios_probatorios(clasificacion: str) -> str:
    """Consulta el Anexo 3 para obtener los medios probatorios requeridos según la clasificación del reclamo."""
    return _buscar_medios_probatorios(clasificacion)


@tool
def consultar_informes_requeridos(clasificacion: str) -> str:
    """Consulta los informes que deben generarse para la investigación según la clasificación del reclamo."""
    return _buscar_informes(clasificacion)


def _buscar_medios_probatorios(clasificacion: str) -> str:
    anexo3 = json.loads(ANEXO3_PATH.read_text(encoding="utf-8"))
    entrada = anexo3.get(clasificacion)

    if not entrada:
        logger.warning("[TOOLS.INVESTIGACION] Clasificación no encontrada en Anexo 3: %s", clasificacion)
        return ""

    comunes = "\n".join(f"- {m['nombre']}" for m in entrada["comunes"])
    medios = "\n".join(f"- {m['nombre']}" for m in entrada["medios"])
    resultado = f"Categoría: {entrada['categoria']}\n\nMedios comunes:\n{comunes}\n\nMedios específicos:\n{medios}"

    logger.info("[TOOLS.INVESTIGACION] Medios probatorios | clasificacion=%s | categoria=%s | medios=%d",
                clasificacion, entrada["categoria"], len(entrada["medios"]))
    return resultado


def _buscar_informes(clasificacion: str) -> str:
    informes = json.loads(INFORMES_PATH.read_text(encoding="utf-8"))
    entrada = informes.get(clasificacion)

    if not entrada:
        logger.warning("[TOOLS.INVESTIGACION] Clasificación no encontrada en informes: %s", clasificacion)
        return ""

    lineas = []
    for i, inf in enumerate(entrada["informes"], 1):
        medios_lista = ", ".join(inf["medios_requeridos"])
        lineas.append(f"{i}. {inf['nombre']} (medios requeridos: {medios_lista})")

    resultado = "\n".join(lineas)

    logger.info("[TOOLS.INVESTIGACION] Informes requeridos | clasificacion=%s | informes=%d",
                clasificacion, len(entrada["informes"]))
    return resultado


def _obtener_informes_struct(clasificacion: str) -> list[dict]:
    """Retorna la lista de informes con su estructura completa (nombre + medios_requeridos)."""
    informes = json.loads(INFORMES_PATH.read_text(encoding="utf-8"))
    entrada = informes.get(clasificacion)

    if not entrada:
        logger.warning("[TOOLS.INVESTIGACION] Clasificación no encontrada en informes: %s", clasificacion)
        return []

    logger.info("[TOOLS.INVESTIGACION] Informes struct | clasificacion=%s | informes=%d",
                clasificacion, len(entrada["informes"]))
    return entrada.get("informes", [])


