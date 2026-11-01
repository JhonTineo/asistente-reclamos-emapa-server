"""Agente de fundamentación normativa.

Dado un ProblemaNormado detectado en un medio probatorio:
  1. Busca en la normativa (Qdrant) los artículos que tratan ese tipo de
     problema, usando una query canónica (concepto, sin cifras). La búsqueda es
     ESCALONADA: primero la norma de atención de reclamos y, si sus artículos no
     alcanzan para argumentar, la norma de calidad (ver `normativa_escalonada`).
  2. Pasa el problema (con sus datos) + los artículos al LLM para que infiera
     qué corresponde hacer y de quién es la responsabilidad. Si el LLM juzga que
     ningún artículo de la norma consultada regula el hallazgo (aplica=false), se
     escala a la siguiente norma en vez de forzar una cita.

"""

import json
import re
import logging
from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.application.services.rag.normativa_escalonada import (
    BuscadorNormativo,
    FuenteNormativa,
    fuentes_configuradas,
)
from app.src.application.services.rag.retriever import Retriever
from app.src.core.model.informe_atencion import ProblemaNormado
from app.src.application.ports.vector_db_port import PuertoBaseVectorial
from app.src.infrastructure.config.settings import settings


logger = logging.getLogger("agent.fundamentacion_normativa")

# Query canónica por tipo de problema (concepto, SIN cifras ni fechas).
# Redactada para la norma de CALIDAD (facturación, lecturas, fugas).
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
    # Tipos que salían SIN consulta canónica (la búsqueda quedaba sin el
    # concepto general del grupo): hallazgos de inspección, record y cortes.
    "fugas": (
        "fuga visible o no visible detectada en la inspección y facturación "
        "según la diferencia de lecturas o el promedio histórico de consumos"
    ),
    "atipico": (
        "consumo atípico: diferencia de lecturas que supera el promedio "
        "histórico y verificación de factores distorsionantes del registro "
        "mediante inspección"
    ),
    "equipo": (
        "estado del medidor, de la caja del medidor o de la conexión "
        "domiciliaria: medidor inoperativo, dañado o caja deteriorada"
    ),
    "mesesPromediados": (
        "facturación por promedio histórico de consumos o asignación de "
        "consumo en lugar de la diferencia de lecturas"
    ),
    "rachaPromediados": (
        "meses consecutivos facturados por promedio histórico de consumos: "
        "máximo de dos meses consecutivos y una vez cada doce meses"
    ),
    "mesesCortados": (
        "servicio cortado o cerrado en el periodo facturado y facturación de "
        "meses sin servicio"
    ),
    "reclamosPrevios": (
        "reclamo previo presentado sobre el mismo periodo o ciclo de "
        "facturación"
    ),
}

# Misma idea para la norma de RECLAMOS, que habla de procedimiento: inspección,
# verificación posterior del medidor, medios de prueba, resolución, pagos en
# exceso, prohibición de cortar/condicionar durante el reclamo.
# OJO: son hipótesis de redacción; se calibran con app/test/rag (gold set).
CONSULTA_RECLAMOS_POR_TIPO = {
    "errorConsumo": (
        "reclamo por consumo elevado: inspección, verificación posterior del "
        "medidor y medios de prueba para declarar el reclamo fundado o infundado"
    ),
    "fugaReparada": (
        "reclamo por consumo elevado con fuga: inspección interna y externa "
        "como medio de prueba y resolución del reclamo"
    ),
    "errorLecturas": (
        "reclamo por lectura o facturación errónea: medios de prueba de "
        "histórico de lecturas y de facturación, y resolución del reclamo"
    ),
    "errorReinstalacion": (
        "retiro o reinstalación del medidor durante el reclamo, verificación "
        "posterior del medidor y su costo"
    ),
    "errorServicio": (
        "servicio cerrado o cortado durante el reclamo: prohibición de cierre "
        "del servicio por los montos reclamados"
    ),
    "cobroIndebido": (
        "devolución de pagos efectuados en exceso, compensación mediante notas "
        "de abono e intereses"
    ),
    "mora": (
        "cobro de intereses y de los montos reclamados mientras el reclamo "
        "no se resuelve: prohibición de condicionar el reclamo al pago previo"
    ),
    "mesesNoPagados": (
        "cobro de montos no reclamados, pago previo y cierre del servicio "
        "durante el reclamo"
    ),
    "fugas": (
        "inspección interna y externa como medio de prueba en el reclamo por "
        "consumo elevado, aviso previo y acta de inspección"
    ),
    "atipico": (
        "inspección y verificación posterior del medidor como medios de prueba "
        "ante un consumo atípico reclamado"
    ),
    "equipo": (
        "verificación posterior del medidor dañado o alterado, costo de la "
        "prueba y declaración de fundado o infundado"
    ),
    "mesesPromediados": (
        "medios de prueba de facturación por promedio o asignación en el "
        "reclamo por consumo y resolución del reclamo"
    ),
    "rachaPromediados": (
        "medios de prueba de facturación por promedio en el reclamo por "
        "consumo y resolución del reclamo"
    ),
    "mesesCortados": (
        "reclamo por consumo facturado con el servicio cerrado: histórico de "
        "cierres y prohibición de cierre durante el reclamo"
    ),
    "reclamosPrevios": (
        "reclamos previos del mismo ciclo de facturación: pruebas e "
        "inspecciones ya realizadas pueden presentarse en el nuevo reclamo"
    ),
}

CONSULTA_POR_FUENTE = {
    "sunass_reclamos": CONSULTA_RECLAMOS_POR_TIPO,
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

    def __init__(self, qdrant: PuertoBaseVectorial, llm_router: LlmRouterService, model: str | None = None):
        self.retriever = Retriever(qdrant)
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT
        self.buscador = BuscadorNormativo(
            retriever=self.retriever,
            store=qdrant,
            fuentes=fuentes_configuradas(settings.normativa_fuentes),
            top_k=settings.normativa_top_k,
            umbral=settings.normativa_umbral_score,
        )

    # ------------------------------------------------------------------ #
    # 1) Búsqueda vectorial (escalonada)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _construir_query(problema: ProblemaNormado, contexto: str, fuente: FuenteNormativa) -> str:
        consultas = CONSULTA_POR_FUENTE.get(fuente.coleccion, CONSULTA_POR_TIPO)
        concepto_general = consultas.get(problema.tipo, "")
        concepto_especifico = _concepto(problema.detalle)
        # El concepto específico va primero (mayor peso semántico); luego el
        # concepto general del grupo, y por último el motivo del reclamo, que
        # aporta el contexto real del caso (p.ej. "fuga reparada") sin el cual
        # no se pueden recuperar los artículos que tratan ese contexto.
        return f"{concepto_especifico}. {concepto_general}. {contexto}".strip(". ")

    def buscar_articulos(self, problema: ProblemaNormado, contexto: str = "", nivel: int = 0) -> list[dict]:
        """Artículos de la primera norma (desde `nivel`) que tenga alguno por
        encima del umbral. Cada resultado lleva su `fuente`."""
        return self.buscador.buscar_desde(
            lambda fuente: self._construir_query(problema, contexto, fuente),
            nivel=nivel,
        )

    # ------------------------------------------------------------------ #
    # 2) Inferencia del LLM
    # ------------------------------------------------------------------ #
    def interpretar(
        self,
        problema: ProblemaNormado,
        articulos: list[dict],
        clasificacion: str = "",
        contexto: str = "",
        fuente: FuenteNormativa | None = None,
    ) -> dict:

        fuente = fuente or (articulos[0].get("fuente") if articulos else None) or self.buscador.fuentes[-1]

        articulos_texto = "\n\n".join(
            f"[Art. {a['payload'].get('numeral') or a['payload'].get('article')} "
            f"del {fuente.nombre_corto}] "
            f"{a['payload'].get('text', '')}"
            for a in articulos
        )

        system = (
            "Eres un analista normativo de EMAPA. Determinas, según "
            f"{fuente.nombre}, qué corresponde hacer ante un HALLAZGO "
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
            "la accion y cita el artículo/numeral (base_legal) en que te apoyas, "
            f"indicando la norma (p. ej. \"Art. 15.5 del {fuente.nombre_corto}\").\n"
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

        response_text = self.llm_router.generar_json(
            mensajes=[
                MensajeLLM(rol="system", contenido=system),
                MensajeLLM(rol="user", contenido=human)
            ],
            modelo_id=self.model_id
        )

        logger.info("RESPUESTA LLM (raw): %s", response_text)

        return self._parse_json(response_text or "")

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
                # Norma de la que sale: sin esto "Art. 14.2" no dice si es del
                # Reglamento de Reclamos o del de Calidad.
                "coleccion": a["fuente"].coleccion if a.get("fuente") else None,
                "norma_corta": a["fuente"].nombre_corto if a.get("fuente") else None,
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
        hallados y rellena el problema in-place.

        ESCALADA: si el LLM juzga que ningún artículo de la norma consultada
        regula el hallazgo, se busca en la siguiente norma (reclamos -> calidad)
        y se vuelve a interpretar. Solo si ninguna norma alcanza, el problema
        queda sin base legal."""
        nivel = self.buscador.nivel_de(articulos)

        while articulos:
            fuente = articulos[0].get("fuente") or self.buscador.fuentes[nivel]
            interp = self.interpretar(problema, articulos, clasificacion, contexto, fuente)
            accion = self._a_texto(interp.get("accion"))
            # Guardarraíl de abstención: si el LLM juzgó que ningún artículo regula
            # el hallazgo (aplica=false) o devolvió "no_determinable", NO se
            # fundamenta; así se evita citar artículos irrelevantes.
            no_aplica = interp.get("aplica") is False or (accion or "").strip().lower() == "no_determinable"
            if not no_aplica:
                problema.articulos = self.articulos_a_payload(articulos)
                problema.accion = accion
                problema.base_legal = self._con_norma(self._a_texto(interp.get("base_legal")), fuente)
                return problema

            logger.info(
                "[%s] el LLM no halló artículo que regule el hallazgo; se escala a la siguiente norma",
                fuente.coleccion,
            )
            siguiente = self.buscar_articulos(problema, contexto, nivel=nivel + 1)
            if not siguiente:
                break
            articulos = siguiente
            nivel = self.buscador.nivel_de(articulos)
            # El frontend debe ver los artículos de la norma con que se argumentó.
            problema.articulos = self.articulos_a_payload(articulos)

        if not articulos:
            problema.accion = (
                "No se hallaron artículos aplicables con relevancia suficiente."
            )
        else:
            problema.accion = "No corresponde: los artículos recuperados no regulan este hallazgo."
        problema.base_legal = None
        return problema

    @staticmethod
    def _con_norma(base_legal: str | None, fuente: FuenteNormativa) -> str | None:
        """Asegura que la cita diga de qué norma es el artículo."""
        if base_legal and fuente.nombre_corto.lower() not in base_legal.lower():
            return f"{base_legal} ({fuente.nombre_corto})"
        return base_legal

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
