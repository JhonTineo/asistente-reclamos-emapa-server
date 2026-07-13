"""Agente de fundamentación normativa.

Dado un ProblemaNormado detectado en un medio probatorio:
  1. Busca en el reglamento SUNASS (Qdrant) los artículos que tratan ese tipo
     de problema, usando una query canónica (concepto, sin cifras).
  2. Pasa el problema (con sus datos) + los artículos al LLM para que infiera
     qué corresponde hacer y de quién es la responsabilidad.

Rellena in-place los campos de fundamentación del ProblemaNormado.
"""

import json
import re
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from app.src.application.adapters.llm import get_llm
from app.src.application.services.rag.retriever import Retriever
from app.src.core.model.informe_atencion import ProblemaNormado

logger = logging.getLogger("agent.fundamentacion_normativa")

COLLECTION = "sunass_reglamento"
TOP_K = 3
UMBRAL_SCORE = 0.5   # descarta artículos poco relevantes (calibrar con casos)

# Query canónica por tipo de problema (concepto, SIN cifras ni fechas: eso
# empeora el match contra el lenguaje jurídico del reglamento).
CONSULTA_POR_TIPO = {
    "errorConsumo": (
        "consumo atípico y facturación elevada por diferencia de lecturas "
        "del medidor"
    ),
    "errorLecturas": (
        "error en la lectura del medidor, consumo negativo y lectura que no "
        "corresponde al periodo"
    ),
    "errorReinstalacion": (
        "cambio o reinstalación del medidor y facturación por el nuevo medidor"
    ),
    "errorServicio": (
        "estado del servicio y del medidor: servicio cortado, inactivo o "
        "medidor inoperativo"
    ),
}


class FundamentacionNormativaAgent:

    def __init__(self, model: str | None = None):
        self.retriever = Retriever()
        self.llm = get_llm(model=model)

    # ------------------------------------------------------------------ #
    # 1) Búsqueda vectorial
    # ------------------------------------------------------------------ #
    def buscar_articulos(self, tipo: str, detalle: str) -> list[dict]:
        query = CONSULTA_POR_TIPO.get(tipo, detalle)
        resultados = self.retriever.retrieve(
            query=query,
            top_k=TOP_K,
            collection_name=COLLECTION,
        )
        # Qdrant devuelve ordenado por score desc; filtramos por umbral.
        return [r for r in resultados if r.get("score", 0) >= UMBRAL_SCORE]

    # ------------------------------------------------------------------ #
    # 2) Inferencia del LLM
    # ------------------------------------------------------------------ #
    def interpretar(
        self,
        problema: ProblemaNormado,
        articulos: list[dict],
        clasificacion: str = "",
    ) -> dict:
        # El numeral (p.ej. "92.2") ya incluye el nº de artículo; si no hay
        # numeral, se cita el artículo (p.ej. "108").
        articulos_texto = "\n\n".join(
            f"[Art. {a['payload'].get('numeral') or a['payload'].get('article')}] "
            f"{a['payload'].get('text', '')}"
            for a in articulos
        )

        system = (
            "Eres un analista normativo de EMAPA. Determinas, según el "
            "Reglamento de Calidad SUNASS, qué corresponde hacer ante un "
            "hallazgo y de quién es la responsabilidad.\n"
            "Reglas:\n"
            "- Basáte ÚNICAMENTE en los artículos proporcionados. No inventes "
            "normas.\n"
            "- Si los artículos no permiten determinar la responsabilidad, usa "
            "\"no_determinable\".\n"
            "- Cita el artículo/numeral en que te apoyas.\n"
            "Responde SOLO con un JSON válido con las claves: accion, "
            "responsable, base_legal, justificacion.\n"
            "responsable debe ser uno de: \"cliente\", \"empresa\", "
            "\"no_determinable\"."
        )

        human = (
            f"Hallazgo detectado: {problema.detalle}\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n\n"
            f"Artículos del reglamento (recuperados):\n{articulos_texto}\n\n"
            "Devuelve SOLO el JSON."
        )

        response = self.llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=human),
        ])

        return self._parse_json(response.content or "")

    @staticmethod
    def _parse_json(texto: str) -> dict:
        match = re.search(r"\{.*\}", texto, re.DOTALL)
        if not match:
            logger.warning("El LLM no devolvió JSON: %s", texto[:200])
            return {}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("JSON inválido del LLM: %s | %s", e, texto[:200])
            return {}

    @staticmethod
    def articulos_a_payload(articulos: list[dict]) -> list[dict]:
        """Normaliza los resultados de Qdrant al formato que se guarda en el
        problema y se envía al frontend."""
        return [
            {
                "article": a["payload"].get("article"),
                "numeral": a["payload"].get("numeral"),
                "score": round(a.get("score", 0), 4),
                "texto": a["payload"].get("text"),
            }
            for a in articulos
        ]

    # ------------------------------------------------------------------ #
    # Fases separadas (para orquestación en streaming)
    # ------------------------------------------------------------------ #
    def fundamentar_articulos(self, problema: ProblemaNormado) -> list[dict]:
        """Fase 1: busca los artículos aplicables y los asigna al problema.
        Devuelve los artículos crudos (necesarios para la interpretación)."""
        articulos = self.buscar_articulos(problema.tipo, problema.detalle)
        problema.articulos = self.articulos_a_payload(articulos)
        return articulos

    def fundamentar_interpretacion(
        self,
        problema: ProblemaNormado,
        articulos: list[dict],
        clasificacion: str = "",
    ) -> ProblemaNormado:
        """Fase 2: infiere acción/responsable/base_legal a partir de los
        artículos hallados y rellena el problema in-place."""
        if not articulos:
            problema.accion = (
                "No se hallaron artículos aplicables con relevancia suficiente."
            )
            problema.responsable = "no_determinable"
            problema.base_legal = None
            return problema

        interp = self.interpretar(problema, articulos, clasificacion)
        problema.accion = interp.get("accion")
        problema.responsable = interp.get("responsable", "no_determinable")
        problema.base_legal = interp.get("base_legal")
        return problema

    # ------------------------------------------------------------------ #
    # Orquestación: busca + interpreta y rellena el problema
    # ------------------------------------------------------------------ #
    def fundamentar(
        self,
        problema: ProblemaNormado,
        clasificacion: str = "",
    ) -> ProblemaNormado:
        articulos = self.fundamentar_articulos(problema)
        self.fundamentar_interpretacion(problema, articulos, clasificacion)
        return problema

    def fundamentar_todos(
        self,
        problemas: list[ProblemaNormado],
        clasificacion: str = "",
    ) -> list[ProblemaNormado]:
        for problema in problemas:
            self.fundamentar(problema, clasificacion)
        return problemas
