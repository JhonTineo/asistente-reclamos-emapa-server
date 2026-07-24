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
    "fugaReparada": (
        "fuga no visible reparada por el usuario y facturación de los meses "
        "afectados según el promedio histórico de consumos"
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

        articulos_texto = "\n\n".join(
            f"[Art. {a['payload'].get('numeral') or a['payload'].get('article')}] "
            f"{a['payload'].get('text', '')}"
            for a in articulos
        )

        system = (
            "Eres un analista normativo de EMAPA. Determinas, según el "
            "Reglamento de Calidad SUNASS, qué corresponde hacer ante un HALLAZGO "
            "concreto.\n"
            "Procede en dos pasos:\n"
            "1. RELEVANCIA: decide si alguno de los artículos proporcionados "
            "REGULA ESE HALLAZGO en particular (no el motivo general del reclamo). "
            "Un artículo es relevante solo si trata directamente la situación del "
            "hallazgo. Ejemplo: si el hallazgo es el registro de un reclamo previo "
            "o un corte de servicio, NO se regula con un artículo sobre fugas, "
            "aunque el motivo del reclamo mencione una fuga.\n"
            "2. Si NINGÚN artículo regula el hallazgo → aplica=false, "
            "accion=\"no_determinable\", base_legal=null. NO fuerces un artículo "
            "que no corresponde. Si al menos uno aplica → aplica=true, determina "
            "la accion y cita el artículo/numeral (base_legal) en que te apoyas.\n"
            "Basáte ÚNICAMENTE en los artículos dados; no inventes normas ni cifras.\n"
            "Responde SOLO con un JSON válido con las claves: aplica (true/false), "
            "accion, base_legal, justificacion."
        )

        human = (
            f"Hallazgo detectado (evalúa la norma contra ESTO): {problema.detalle}\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n"
            + (f"Motivo del reclamo (solo contexto, NO es el hallazgo): {contexto}\n" if contexto else "")
            + f"\nArtículos del reglamento (recuperados):\n{articulos_texto}\n\n"
            "Primero decide la RELEVANCIA de los artículos frente al HALLAZGO; si "
            "ninguno lo regula, responde aplica=false y accion=\"no_determinable\". "
            "Si el hallazgo indica una fuga no visible ya reparada, la facturación "
            "que corresponde es por promedio histórico.\n\n"
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
        accion = self._a_texto(interp.get("accion"))
        # Guardarraíl de abstención: si el LLM juzgó que ningún artículo regula el
        # hallazgo (aplica=false) o devolvió "no_determinable", NO se fundamenta;
        # así se evita citar artículos irrelevantes.
        no_aplica = interp.get("aplica") is False or (accion or "").strip().lower() == "no_determinable"
        if no_aplica:
            problema.accion = "No corresponde: los artículos recuperados no regulan este hallazgo."
            problema.base_legal = None
        else:
            problema.accion = accion
            problema.base_legal = self._a_texto(interp.get("base_legal"))
        return problema

    @staticmethod
    def _a_texto(valor) -> str | None:
        """Normaliza un campo que el LLM a veces devuelve como lista en vez de
        string. Distintos modelos (sobre todo los de OpenRouter) devuelven, por
        ejemplo, base_legal=[] o ["Art. 92.2", "Art. 91"] en lugar de un string.
        Une las listas y trata la lista vacía como None, para que encaje con el
        schema (str | None) sin romper la validación."""
        if valor is None:
            return None
        if isinstance(valor, str):
            return valor or None
        if isinstance(valor, (list, tuple)):
            partes = [str(v).strip() for v in valor if str(v).strip()]
            return ", ".join(partes) or None
        return str(valor)

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
