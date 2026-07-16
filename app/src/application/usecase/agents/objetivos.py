"""Agente que define los objetivos de investigación de un reclamo.

A partir del motivo (lo que reclama el cliente) y la clasificación, genera una
lista de objetivos concretos y verificables. Cada objetivo se marca como
`determinante` cuando su resultado decide el veredicto FUNDADO/INFUNDADO.

Los objetivos se generan al buscar el reclamo y guían toda la investigación.
"""

import json
import re
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from app.src.application.adapters.llm import get_llm, log_uso_llm
from app.src.core.model.informe_atencion import ObjetivoInvestigacion

logger = logging.getLogger("agent.objetivos")

# Medios probatorios disponibles y qué información tiene cada uno. Se usa para
# que el LLM asocie cada objetivo al medio que puede responderlo, y para que
# entienda de antemano el alcance real de cada medio (evita objetivos que
# ningún medio puede verificar).
MEDIOS = {
    "tarjeta_lectura": (
        "Lectura del medidor de cada mes, consumos atipícos, problemas en el medidor"
    ),
    "inspeccion_interna": (
        "Inspección del interior del predio, fugas despues del medidor, estado de las instalaciones sanitarias, y observaciones del inspector."
    ),
    "inspeccion_externa": (
        "Inspección de la conexión externa, estado del medidor y de la caja, fugas antes del medidor, y observaciones del inspector."
    ),
    "corte_reapertura": (
        "Historial de cortes del servicio por deuda, reaperturas, "
        "prórrogas, reclamos previos y observaciones para citar."
    ),
    "record_facturacion": (
        "Facturación de cada mes, tipo de facturación (promedio o lectura), cambios de facturación y observaciones."
    ),
}


class ObjetivosAgent:

    def __init__(self, model: str | None = None):
        self.llm = get_llm(model=model)

    def generar(self, motivo: str, clasificacion: str = "") -> list[ObjetivoInvestigacion]:
        if not motivo or not motivo.strip():
            logger.warning("[OBJETIVOS] Motivo vacío; no se generan objetivos")
            return []

        medios_texto = "\n".join(f"- {medio}: {desc}" for medio, desc in MEDIOS.items())
        system = (
            "Eres un analista de reclamos de EMAPA. A partir del motivo del reclamo "
            "defines los OBJETIVOS de investigación: qué verificar concretamente en los "
            "medios probatorios para determinar si el reclamo procede.\n\n"
            "Medios probatorios disponibles y qué información tiene cada uno:\n"
            f"{medios_texto}\n\n"
            
            "Responde SOLO con el JSON (lista de objetos con las claves \"descripcion\", "
            "\"medio\", \"determinante\"), sin texto adicional."
        )
        human = (
            f"Motivo del reclamo:\n{motivo}\n\n"
            f"Clasificación: {clasificacion or 'no especificada'}\n\n"
            "Devuelve SOLO el JSON (lista de objetivos). /no_think"
        )

        logger.debug("[PROMPT objetivos][SYSTEM]\n%s", system)
        logger.debug("[PROMPT objetivos][HUMAN]\n%s", human)

        response = self.llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=human),
        ])
        log_uso_llm(logger, "objetivos", response)

        objetivos = self._parse(response.content or "")
        logger.info("[OBJETIVOS] %d objetivo(s) generados", len(objetivos))
        return objetivos

    @staticmethod
    def _parse(texto: str) -> list[ObjetivoInvestigacion]:
        match = re.search(r"\[.*\]", texto, re.DOTALL)
        if not match:
            logger.warning("[OBJETIVOS] El LLM no devolvió una lista JSON: %s", texto[:200])
            return []
        try:
            crudos = json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("[OBJETIVOS] JSON inválido: %s | %s", e, texto[:200])
            return []

        objetivos: list[ObjetivoInvestigacion] = []
        for i, o in enumerate(crudos, start=1):
            if not isinstance(o, dict) or not o.get("descripcion"):
                continue
            medio = o.get("medio")
            objetivos.append(
                ObjetivoInvestigacion(
                    id=i,
                    descripcion=str(o["descripcion"]).strip(),
                    medio=medio if medio in MEDIOS else None,
                    determinante=bool(o.get("determinante", False)),
                )
            )
        return objetivos
