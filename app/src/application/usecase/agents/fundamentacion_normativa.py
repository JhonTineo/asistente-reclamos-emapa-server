"""Agente de fundamentación normativa.

Dado un ProblemaNormado detectado en un medio probatorio:
  1. Busca en el reglamento SUNASS (Qdrant) los artículos que tratan ese tipo
     de problema, usando una query canónica (concepto, sin cifras).
  2. Pasa el problema (con sus datos) + los artículos al LLM para que infiera
     qué corresponde hacer y de quién es la responsabilidad.

"""

import json
import re
import logging
from langchain_core.messages import SystemMessage, HumanMessage
from app.src.application.adapters.llm import get_llm, log_uso_llm
from app.src.application.services.rag.retriever import Retriever
from app.src.core.model.informe_atencion import ProblemaNormado

logger = logging.getLogger("agent.fundamentacion_normativa")

COLLECTION = "sunass_reglamento"
TOP_K = 3
UMBRAL_SCORE = 0.5   # descarta artículos poco relevantes (calibrar con casos)

# Query canónica por tipo de problema (concepto, SIN cifras ni fechas)
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
    "cobroIndebido": (
        "cobro indebido por servicio no prestado, facturación de alcantarillado "
        "o desagüe sin conexión al servicio"
    ),
    "mora": (
        "cobro de intereses moratorios y recargos por pago fuera de plazo del "
        "servicio de agua"
    ),
    "mesesNoPagados": (
        "deuda pendiente de pago, saldos vencidos y facturación de meses "
        "anteriores no cancelados"
    ),
}


def _concepto(detalle: str) -> str:
    """Extrae el concepto del hallazgo (lo que va antes de ': detectado en...'),
    que es mucho más específico que `tipo` (el grupo). `tipo` agrupa varios
    conceptos distintos (p.ej. "Consumo excesivo" y "No registro consumo y/o
    lectura" caen ambos en un mismo grupo), así que usar solo la query del
    grupo hace que hallazgos muy distintos disparen la MISMA búsqueda vectorial
    y traigan artículos que no tratan del hallazgo real. Si no hay ':' (caso de
    saldo-detalle, cuyo detalle ya es una oración completa), se usa el texto
    completo."""
    return detalle.split(":", 1)[0].strip()


class FundamentacionNormativaAgent:

    def __init__(self, model: str | None = None):
        self.retriever = Retriever()
        self.llm = get_llm(model=model)

    # ------------------------------------------------------------------ #
    # 1) Búsqueda vectorial
    # ------------------------------------------------------------------ #
    def buscar_articulos(self, problema: ProblemaNormado, contexto: str = "") -> list[dict]:
        concepto_general = CONSULTA_POR_TIPO.get(problema.tipo, "")
        concepto_especifico = _concepto(problema.detalle)
        # El concepto específico va primero (mayor peso semántico); luego el
        # concepto general del grupo, y por último el motivo del reclamo, que
        # aporta el contexto real del caso (p.ej. "fuga reparada") sin el cual
        # no se pueden recuperar los artículos que tratan ese contexto.
        query = f"{concepto_especifico}. {concepto_general}. {contexto}".strip(". ")
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
        contexto: str = "",
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
            "hallazgo.\n"
            "Reglas:\n"
            "- Basáte ÚNICAMENTE en los artículos proporcionados. No inventes "
            "normas.\n"
            "- Si los artículos no permiten determinar qué acción tomar, usa "
            "\"no_determinable\" en accion.\n"
            "- Cita el artículo/numeral en que te apoyas.\n"
            "Responde SOLO con un JSON válido con las claves: accion, "
            "base_legal, justificacion."
        )

        human = (
            (f"Motivo del reclamo (lo que dice el cliente): {contexto}\n\n" if contexto else "")
            + f"Hallazgo detectado: {problema.detalle}\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n\n"
            f"Artículos del reglamento (recuperados):\n{articulos_texto}\n\n"
            "Ten en cuenta el motivo del reclamo para que tu conclusión sea "
            "coherente con lo que realmente ocurrió (p.ej. si el cliente indica "
            "que ya reparó una fuga, evalúa la facturación considerando eso).\n\n"
            "Devuelve SOLO el JSON."
        )

        # --- Depuración: prompt exacto enviado al modelo -------------------
        logger.info(
            "PROMPT LLM fundamentacion_normativa\n"
            "===================== SYSTEM =====================\n%s\n"
            "===================== HUMAN ======================\n%s\n"
            "==================================================\n"
            "articulos_recuperados=%d",
            system,
            human,
            len(articulos),
        )

        response = self.llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=human),
        ])
        log_uso_llm(logger, "fundamentacion", response)

        logger.info("RESPUESTA LLM (raw): %s", response.content)

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
    def fundamentar_articulos(self, problema: ProblemaNormado, contexto: str = "") -> list[dict]:
        """Fase 1: busca los artículos aplicables y los asigna al problema.
        Devuelve los artículos (que se utilizan en la interpretación)."""
        articulos = self.buscar_articulos(problema, contexto)
        problema.articulos = self.articulos_a_payload(articulos)
        return articulos

    def fundamentar_interpretacion(
        self,
        problema: ProblemaNormado,
        articulos: list[dict],
        clasificacion: str = "",
        contexto: str = "",
    ) -> ProblemaNormado:
        """Fase 2: infierencia acción/base_legal a partir de los artículos
        hallados y rellena el problema in-place."""
        if not articulos:
            problema.accion = (
                "No se hallaron artículos aplicables con relevancia suficiente."
            )
            problema.base_legal = None
            return problema

        interp = self.interpretar(problema, articulos, clasificacion, contexto)
        problema.accion = interp.get("accion")
        problema.base_legal = interp.get("base_legal")
        return problema

    # ------------------------------------------------------------------ #
    # Fundamentación completa (artículos + interpretación)
    # ------------------------------------------------------------------ #
    def fundamentar(
        self,
        problema: ProblemaNormado,
        clasificacion: str = "",
        contexto: str = "",
    ) -> ProblemaNormado:
        articulos = self.fundamentar_articulos(problema, contexto)
        self.fundamentar_interpretacion(problema, articulos, clasificacion, contexto)
        return problema

    def fundamentar_todos(
        self,
        problemas: list[ProblemaNormado],
        clasificacion: str = "",
        contexto: str = "",
    ) -> list[ProblemaNormado]:
        for problema in problemas:
            self.fundamentar(problema, clasificacion, contexto)
        return problemas
