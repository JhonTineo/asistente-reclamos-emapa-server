"""Paso de fundamentación normativa.

Dado un ProblemaNormado detectado en un medio probatorio:
  1. Busca en el reglamento SUNASS (Qdrant) los artículos que tratan ese tipo
     de problema, usando una query canónica (concepto, sin cifras).
  2. Pasa el problema (con sus datos) + los artículos al LLM para que infiera
     qué corresponde hacer y de quién es la responsabilidad.

"""

import json
import re
import logging
from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.application.services.rag.retriever import Retriever
from app.src.core.model.informe_atencion import ProblemaNormado
from app.src.application.services.pre_proces.constataciones import HECHOS_MES_RECLAMADO, LIMITACIONES
from app.src.application.ports.vector_db_port import PuertoBaseVectorial


logger = logging.getLogger("paso.fundamentacion")

# Hechos que entran SIEMPRE en la fundamentación, por regla y no por elección
# del modelo: la lectura y la facturación del mes reclamado (son la respuesta
# directa a un reclamo de consumo; el selector llegó a dejar fuera la lectura
# que comparaba el consumo con el promedio) y las limitaciones de la
# verificación (si se omiten, lo visto en la inspección externa se generaliza
# a todo el predio).
SIEMPRE_INCLUIDOS = LIMITACIONES | HECHOS_MES_RECLAMADO
MAX_ADICIONALES = 2   # hechos que el modelo puede sumar a los siempre incluidos

COLLECTION = "sunass_reglamento"
TOP_K = 3
UMBRAL_SCORE = 0.5   # descarta artículos poco relevantes (calibrar con casos)

# Query canónica por tipo de problema (concepto, SIN cifras ni fechas)
CONSULTA_POR_TIPO = {
    "errorConsumo": (
        "consumo atípico y facturación elevada por diferencia de lecturas "
        "del medidor"
    ),
    "descensoConsumo": (
        "descenso de consumo posterior a un consumo elevado, evaluación de la "
        "serie de lecturas y facturación sin atribuir una causa no acreditada"
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
    "fugaNoDetectada": (
        "inspección sin detección de fugas; alcance probatorio de la observación"
    ),
    "fugaSospechada": (
        "sospecha no confirmada de fuga y necesidad de verificación mediante inspección"
    ),
    "fugaReferida": (
        "fuga referida por el usuario o un tercero, no confirmada por inspección"
    ),
    "contradiccionFuga": (
        "contradicción entre el campo estructurado y las observaciones de una inspección"
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
    # --- constataciones (hechos neutros o favorables, ver constataciones.py) ---
    "lecturaMesReclamado": (
        "facturación del consumo por diferencia de lecturas del medidor; lectura "
        "real registrada en el periodo reclamado"
    ),
    "facturacionMesReclamado": (
        "facturación por diferencia de lecturas con medidor operativo; consumo "
        "medido del mes reclamado"
    ),
    "sinLecturaMesReclamado": (
        "ausencia de lectura del medidor en el periodo; facturación por promedio "
        "o asignación de consumo"
    ),
    "sinFacturacionMesReclamado": (
        "periodo sin registro de facturación; verificación del cobro reclamado"
    ),
    "tendenciaCreciente": (
        "evolución del consumo histórico del predio y variación del consumo "
        "registrado por el medidor"
    ),
    "medidorReciente": (
        "instalación o cambio de medidor y facturación con el nuevo medidor"
    ),
    "rebajaAplicada": (
        "rebaja o refacturación aplicada al recibo como resultado de un reclamo"
    ),
    "estadoMedidorInspeccion": (
        "verificación del funcionamiento del medidor en la inspección; medidor "
        "operativo que registra correctamente el consumo"
    ),
    "fugasInspeccionExterna": (
        "inspección externa de la conexión domiciliaria sin fugas"
    ),
    "estadoConexionInspeccion": (
        "estado de la caja del medidor y de la conexión domiciliaria"
    ),
    "inspeccionInternaRealizada": (
        "inspección interna de las instalaciones sanitarias del predio"
    ),
    "inspeccionInternaSinAcceso": (
        "el usuario no permite o no atiende la inspección interna; la empresa "
        "resuelve el reclamo con los medios probatorios disponibles"
    ),
    "prorrogasCorte": (
        "prórroga del corte del servicio por deuda mientras se tramita el reclamo"
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



class PasoFundamentacion:

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

        human = (
            f"Hallazgo detectado (evalúa la norma contra ESTO): {problema.detalle}\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n"
            + (f"Motivo del reclamo (solo contexto, NO es el hallazgo): {contexto}\n" if contexto else "")
            + f"\nArtículos del reglamento (recuperados):\n{articulos_texto}\n\n"
            "Primero decide la RELEVANCIA de los artículos frente al HALLAZGO; si "
            "ninguno lo regula, responde aplica=false y accion=\"no_determinable\". "
            "No infieras una fuga, su visibilidad o una reparación a partir de un "
            "descenso de consumo. Una reparación solo puede afirmarse si otra "
            "fuente la acredita expresamente.\n\n"
            "Devuelve SOLO el JSON."
        )

        response_text = constructor_contexto.llamar(
            "fundamentacion_interpretacion", self.llm_router, self.model_id, entrada=human,
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
        acoplar el paso al servicio de investigación (evita import circular)."""
        if not informe or not getattr(informe, "objetivos", None):
            return set()
        return {medio for o in informe.objetivos if o.determinante
                for medio in o.medios_relacionados}

    @staticmethod
    def candidatos(informe) -> list[tuple[str, ProblemaNormado]]:
        """(medio_id, hecho) candidatos a fundamentar, en orden de bloque estable:
        todos los hechos de los medios determinantes y, de los demás medios,
        los hechos del mes reclamado (lectura y facturación). Estos últimos son
        el núcleo de un reclamo de consumo y no deben depender de que su medio
        haya quedado marcado como determinante en los objetivos."""
        medios_det = PasoFundamentacion._medios_determinantes(informe)
        if not medios_det:
            return []
        pares: list[tuple[str, ProblemaNormado]] = []
        for bloque in informe.bloques:
            for hecho in bloque.hechos:
                if bloque.medio_id in medios_det or hecho.tipo in HECHOS_MES_RECLAMADO:
                    pares.append((bloque.medio_id, hecho))
        return pares

    @staticmethod
    def pool_determinante(informe) -> list[ProblemaNormado]:
        """Lista completa de hechos candidatos. Es el conjunto de tarjetas que
        ve el front; la selección marca `seleccionado` sobre estos mismos objetos."""
        return [h for _, h in PasoFundamentacion.candidatos(informe)]

    def seleccionar_determinantes(self, informe) -> list[ProblemaNormado]:
        """Hechos que sustentan la fundamentación: los SIEMPRE_INCLUIDOS (por
        regla) más los que el LLM elija, de la lista de hechos de los medios
        determinantes agrupados por objetivo, por su relación DIRECTA con el
        motivo (hasta MAX_ADICIONALES). Marca `seleccionado=True` en ellos
        (in-place) y los devuelve, con los siempre incluidos primero. NO envía
        el resumen del medio."""
        medios_det = self._medios_determinantes(informe)
        if not medios_det:
            logger.info("[FUNDAMENTACION] Sin medios determinantes; nada que seleccionar")
            return []

        # Pool estable y su medio de origen (para agrupar por objetivo por índice).
        pares = self.candidatos(informe)
        pool: list[ProblemaNormado] = [h for _, h in pares]
        medio_de_pool: list[str] = [m for m, _ in pares]
        if not pool:
            logger.info("[FUNDAMENTACION] Medios determinantes sin hechos; nada que seleccionar")
            return []

        idxs_por_medio: dict[str, list[int]] = {}
        for i, mid in enumerate(medio_de_pool):
            idxs_por_medio.setdefault(mid, []).append(i)

        # Primero los del mes reclamado y después las demás limitaciones: en ese
        # orden llegan a la redacción, que empieza por el mes en disputa.
        fijos = ([i for i, p in enumerate(pool) if p.tipo in HECHOS_MES_RECLAMADO]
                 + [i for i, p in enumerate(pool)
                    if p.tipo in SIEMPRE_INCLUIDOS and p.tipo not in HECHOS_MES_RECLAMADO])

        def linea(i: int) -> str:
            clase = "hecho verificado" if pool[i].clase == "constatacion" else "problema"
            marca = " — SIEMPRE INCLUIDO" if i in fijos else ""
            return f"  [{i}] ({clase}{marca}) {pool[i].detalle}"

        # Prompt: motivo + problemas AGRUPADOS POR OBJETIVO determinante (su
        # pregunta como encabezado + los problemas de su medio, indexados).
        grupos: list[str] = []
        cubiertos: set[int] = set()
        for o in informe.objetivos:
            if not o.determinante:
                continue
            lineas = [f"Objetivo: {o.descripcion}"]
            idxs = [i for medio in o.medios_relacionados
                    for i in idxs_por_medio.get(medio, [])]
            if idxs:
                lineas += [linea(i) for i in idxs]
            else:
                lineas.append("  (sin hechos registrados en este medio)")
            cubiertos.update(idxs)
            grupos.append("\n".join(lineas))
        resto = [i for i in range(len(pool)) if i not in cubiertos]
        if resto:
            grupos.append("\n".join(
                ["Hechos del mes reclamado (de otros medios):"] + [linea(i) for i in resto]
            ))

        # Si todos los candidatos ya entran por regla, no hay nada que elegir.
        indices: list[int] = []
        if len(fijos) < len(pool):
            human = (
                "Motivo del reclamo (lo que el usuario alega; no está verificado):\n"
                f"{informe.motivo or 'no especificado'}\n\n"
                f"Hechos agrupados por objetivo:\n\n" + "\n\n".join(grupos) + "\n\n"
                f"Devuelve SOLO el JSON con los índices de los hechos ADICIONALES "
                f"(ninguno, 1 o {MAX_ADICIONALES}) que deciden el caso; no repitas los "
                "marcados SIEMPRE INCLUIDO."
            )
            response_text = constructor_contexto.llamar(
                "fundamentacion_seleccion", self.llm_router, self.model_id,
                entrada=human, codreclamo=informe.reclamo,
            )
            logger.info("RESPUESTA LLM seleccion (raw): %s", response_text)
            indices = [i for i in self._parse_indices(response_text or "", len(pool))
                       if i not in fijos][:MAX_ADICIONALES]

        # Primero los siempre incluidos (el párrafo empieza por el mes reclamado).
        seleccionados = [pool[i] for i in fijos] + [pool[i] for i in indices]
        for p in seleccionados:
            p.seleccionado = True
        logger.info(
            "[FUNDAMENTACION] %d hecho(s) seleccionado(s) de %d (%d por regla, %d elegidos)",
            len(seleccionados), len(pool), len(fijos), len(indices),
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

    def marcar_aplica(
        self,
        problema: ProblemaNormado,
        articulos_raw: list[dict],
        clasificacion: str = "",
        contexto: str = "",
    ) -> list[dict]:
        """De los artículos recuperados por RAG, pide al LLM cuáles REGULAN el
        problema y devuelve el payload de artículos con un flag `aplica` por cada
        uno (y `manual=False`). Es la relevancia por artículo que luego el usuario
        puede curar en el front."""
        payload = self.articulos_a_payload(articulos_raw)
        for a in payload:
            a["aplica"] = False
            a["manual"] = False
        if not payload:
            return payload

        listado = "\n".join(
            f"[{i}] Art. {a['numeral'] or a['article']}: {a['texto']}"
            for i, a in enumerate(payload)
        )
        human = (
            f"Hallazgo: {problema.detalle}\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n"
            + (f"Motivo (contexto): {contexto}\n" if contexto else "")
            + f"\nArtículos:\n{listado}\n\n"
            "Devuelve SOLO el JSON con los índices de los artículos que aplican."
        )
        logger.info(
            "PROMPT LLM marcar_aplica | hallazgo=%s | articulos=%d", problema.detalle, len(payload),
        )
        response_text = constructor_contexto.llamar(
            "fundamentacion_aplicabilidad", self.llm_router, self.model_id, entrada=human,
        )
        logger.info("RESPUESTA LLM marcar_aplica (raw): %s", response_text)
        for i in self._parse_indices(response_text or "", len(payload)):
            payload[i]["aplica"] = True
        return payload

    def redactar_parrafo(
        self,
        problemas: list[ProblemaNormado],
        motivo: str = "",
        clasificacion: str = "",
    ) -> str:
        """Fase final: UN párrafo de fundamentación normativa para los problemas
        determinantes seleccionados. Cita SOLO los artículos marcados `aplica`
        (por la relevancia o por el usuario); si ninguno aplica, se apoya en los
        hechos."""
        secciones: list[str] = []
        for problema in problemas:
            aplicables = [a for a in (problema.articulos or []) if a.get("aplica")]
            if aplicables:
                arts = "\n".join(
                    f"    [Art. {a.get('numeral') or a.get('article')}] {a.get('texto', '')}"
                    for a in aplicables
                )
            else:
                arts = "    (sin artículos aplicables)"
            clase = "Hecho verificado" if problema.clase == "constatacion" else "Hallazgo"
            secciones.append(f"- {clase}: {problema.detalle}\n  Artículos aplicables:\n{arts}")
        hallazgos_texto = "\n\n".join(secciones)

        human = (
            "ALEGACIÓN del usuario (motivo del reclamo; NO está verificada: no afirmes "
            f"sus cifras ni sus causas como hechos):\n{motivo or 'no especificado'}\n\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n\n"
            f"Hechos determinantes y su normativa recuperada:\n\n{hallazgos_texto}\n\n"
            "Redacta el párrafo de fundamentación normativa."
        )

        texto = constructor_contexto.llamar(
            "fundamentacion_parrafo", self.llm_router, self.model_id, entrada=human,
        )
        return (texto or "").strip()
