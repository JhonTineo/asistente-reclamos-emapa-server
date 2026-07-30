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
from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.application.services.rag.retriever import Retriever
from app.src.core.model.informe_atencion import ProblemaNormado
from app.src.application.ports.vector_db_port import PuertoBaseVectorial


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
    "fugaNoVisible": (
        "fuga no visible detectada en la inspección; si el usuario la repara en "
        "el plazo, los consumos afectados se facturan según el promedio histórico"
    ),
    "fugaVisible": (
        "fuga visible a través de los puntos de salida de agua del predio; la "
        "empresa prestadora factura según la diferencia de lecturas del medidor"
    ),
    "fugas": (
        "fuga de agua hallada en la inspección del predio y su efecto en la "
        "facturación por diferencia de lecturas o por promedio histórico"
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

    def __init__(self, qdrant: PuertoBaseVectorial, llm_router: LlmRouterService, model: str | None = None):
        self.retriever = Retriever(qdrant)
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT

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

    # ================================================================== #
    # Flujo NUEVO: selección de problemas determinantes + párrafo único
    # ------------------------------------------------------------------ #
    # En lugar de fundamentar TODOS los problemas de los medios determinantes
    # (que arrastra hallazgos de contexto y cita artículos flojos), se hace:
    #   1) de la lista de problemas de los medios determinantes (agrupados por
    #      objetivo), el LLM selecciona los 1-3 con relación DIRECTA con el motivo;
    #   2) se recuperan artículos por cada problema seleccionado (RAG por tipo);
    #   3) se redacta UN párrafo de fundamentación normativa.
    # El resto de problemas se muestran igual (tarjetas), pero sin artículos.
    # ================================================================== #
    @staticmethod
    def _medios_determinantes(informe) -> set[str]:
        """Medios de los objetivos determinantes. Se calcula local para no
        acoplar el agente al servicio de investigación (evita import circular)."""
        if not informe or not getattr(informe, "objetivos", None):
            return set()
        return {o.medio for o in informe.objetivos if o.determinante and o.medio}

    @staticmethod
    def pool_determinante(informe) -> list[ProblemaNormado]:
        """Lista completa de problemas de los medios determinantes, en orden de
        bloque estable. Es el conjunto de tarjetas que ve el front; la selección
        marca `seleccionado` sobre estos mismos objetos."""
        medios_det = FundamentacionNormativaAgent._medios_determinantes(informe)
        pool: list[ProblemaNormado] = []
        for bloque in informe.bloques:
            if bloque.medio_id in medios_det:
                pool.extend(bloque.problemas)
        return pool

    def seleccionar_determinantes(self, informe) -> list[ProblemaNormado]:
        """De la lista de problemas de los medios determinantes (agrupados por
        objetivo, con el motivo como contexto), pide al LLM los 1-3 problemas con
        relación DIRECTA con el motivo. Marca `seleccionado=True` en esos
        problemas (in-place) y los devuelve. NO envía el resumen del medio."""
        medios_det = self._medios_determinantes(informe)
        if not medios_det:
            logger.info("[FUNDAMENTACION] Sin medios determinantes; nada que seleccionar")
            return []

        # Pool estable y su medio de origen (para agrupar por objetivo por índice).
        pool: list[ProblemaNormado] = []
        medio_de_pool: list[str] = []
        for bloque in informe.bloques:
            if bloque.medio_id in medios_det:
                for p in bloque.problemas:
                    pool.append(p)
                    medio_de_pool.append(bloque.medio_id)
        if not pool:
            logger.info("[FUNDAMENTACION] Medios determinantes sin problemas; nada que seleccionar")
            return []

        idxs_por_medio: dict[str, list[int]] = {}
        for i, mid in enumerate(medio_de_pool):
            idxs_por_medio.setdefault(mid, []).append(i)

        # Prompt: motivo + problemas AGRUPADOS POR OBJETIVO determinante (su
        # pregunta como encabezado + los problemas de su medio, indexados).
        grupos: list[str] = []
        for o in informe.objetivos:
            if not o.determinante:
                continue
            lineas = [f"Objetivo: {o.descripcion}"]
            idxs = idxs_por_medio.get(o.medio, [])
            if idxs:
                lineas += [f"  [{i}] {pool[i].detalle}" for i in idxs]
            else:
                lineas.append("  (sin problemas registrados en este medio)")
            grupos.append("\n".join(lineas))

        system = (
            "Eres un analista de reclamos de EMAPA. Debes seleccionar, de la lista "
            "de PROBLEMAS agrupados por objetivo, los 1 a 3 problemas con relación "
            "DIRECTA con el motivo del reclamo y que, según el Reglamento de Calidad "
            "SUNASS, deciden si corresponde corregir la facturación.\n"
            "Reglas:\n"
            "- Elige los MÍNIMOS que deciden el caso (entre 1 y 3); descarta "
            "problemas de contexto, de meses lejanos o ajenos al motivo.\n"
            "- Refiérete a cada problema elegido por su número de índice [n].\n"
            "Responde SOLO con un JSON: una lista de enteros con los índices "
            "elegidos (p. ej. [0, 2])."
        )
        human = (
            f"Motivo del reclamo:\n{informe.motivo or 'no especificado'}\n\n"
            f"Problemas agrupados por objetivo:\n\n" + "\n\n".join(grupos) + "\n\n"
            "Devuelve SOLO el JSON con los índices de los 1-3 problemas determinantes."
        )

        logger.info(
            "PROMPT LLM seleccionar_determinantes\n"
            "===================== SYSTEM =====================\n%s\n"
            "===================== HUMAN ======================\n%s\n"
            "==================================================",
            system, human,
        )
        response_text = self.llm_router.generar_json(
            mensajes=[
                MensajeLLM(rol="system", contenido=system),
                MensajeLLM(rol="user", contenido=human),
            ],
            modelo_id=self.model_id,
        )
        logger.info("RESPUESTA LLM seleccion (raw): %s", response_text)

        indices = self._parse_indices(response_text or "", len(pool))
        seleccionados = [pool[i] for i in indices]
        for p in seleccionados:
            p.seleccionado = True
        logger.info(
            "[FUNDAMENTACION] %d problema(s) determinante(s) seleccionado(s) de %d",
            len(seleccionados), len(pool),
        )
        return seleccionados

    @staticmethod
    def _parse_indices(texto: str, n: int) -> list[int]:
        """Extrae la lista de índices [n] elegidos por el LLM (admite enteros o
        objetos {"indice": n}); descarta los fuera de rango y limita a 3."""
        match = re.search(r"\[.*\]", texto, re.DOTALL)
        if not match:
            logger.warning("[FUNDAMENTACION] selección sin lista JSON: %s", texto[:200])
            return []
        try:
            crudos = json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("[FUNDAMENTACION] JSON de selección inválido: %s | %s", e, texto[:200])
            return []
        indices: list[int] = []
        for v in crudos:
            if isinstance(v, dict):
                v = v.get("indice", v.get("index"))
            try:
                i = int(v)
            except (TypeError, ValueError):
                continue
            if 0 <= i < n and i not in indices:
                indices.append(i)
        return indices[:3]

    def redactar_parrafo(
        self,
        problemas: list[ProblemaNormado],
        articulos_por_problema: list[list[dict]],
        motivo: str = "",
        clasificacion: str = "",
    ) -> str:
        """Fase final: UN párrafo de fundamentación normativa para los problemas
        determinantes seleccionados, citando SOLO los artículos provistos que
        realmente regulan cada problema (o solo los hechos si ninguno aplica)."""
        secciones: list[str] = []
        for problema, articulos in zip(problemas, articulos_por_problema):
            if articulos:
                arts = "\n".join(
                    f"    [Art. {a['payload'].get('numeral') or a['payload'].get('article')}] "
                    f"{a['payload'].get('text', '')}"
                    for a in articulos
                )
            else:
                arts = "    (no se recuperaron artículos con relevancia suficiente)"
            secciones.append(f"- Hallazgo: {problema.detalle}\n  Artículos recuperados:\n{arts}")
        hallazgos_texto = "\n\n".join(secciones)

        system = (
            "Eres un analista normativo de EMAPA. Redactas el PÁRRAFO de "
            "fundamentación normativa de un informe de atención, según el "
            "Reglamento de Calidad SUNASS (RCD 061-2018-SUNASS-CD).\n"
            "Reglas:\n"
            "- Escribe UN SOLO párrafo formal, CONCRETO y sin relleno (sin viñetas "
            "ni JSON, sin título).\n"
            "- Nombra el hecho concreto y cita el/los artículo(s) recuperado(s) que "
            "REGULAN ese hecho (por su numeral); puedes citar más de uno si ambos "
            "aplican. Di qué corresponde facturar según la norma.\n"
            "- TERMINA una vez enunciado qué manda la norma. NO agregues una oración "
            "de cierre especulativa o editorial que vaya más allá de la norma (p. ej. "
            "conjeturar que una reparación «podría haber sido necesaria» o especular "
            "sobre las causas del consumo): no aporta y alarga el párrafo.\n"
            "- Si NINGÚN artículo recuperado regula el hecho, fundaméntalo solo por "
            "los hechos; NO inventes artículos ni cifras que no estén en los datos.\n"
            "- No adelantes el veredicto (FUNDADO/INFUNDADO): eso lo decide la "
            "conclusión."
        )
        human = (
            f"Motivo del reclamo:\n{motivo or 'no especificado'}\n\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n\n"
            f"Hallazgos determinantes y su normativa recuperada:\n\n{hallazgos_texto}\n\n"
            "Redacta el párrafo de fundamentación normativa."
        )

        logger.info(
            "PROMPT LLM redactar_parrafo\n"
            "===================== SYSTEM =====================\n%s\n"
            "===================== HUMAN ======================\n%s\n"
            "==================================================",
            system, human,
        )
        texto = self.llm_router.generar_texto(
            mensajes=[
                MensajeLLM(rol="system", contenido=system),
                MensajeLLM(rol="user", contenido=human),
            ],
            modelo_id=self.model_id,
        )
        return (texto or "").strip()
