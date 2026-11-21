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

# Reglamento de Calidad + Reglamento General de Reclamos (ver NORMAS en
# chunk_and_index.py). Se busca en ambas y se fusiona por score.
COLECCIONES = ("sunass_reglamento", "sunass_reclamos")
# 5 candidatos para marcar_aplica (recall@3=77% -> recall@5=81% en la
# evaluación); el LLM descarta los que no regulan el hallazgo.
TOP_K = 5
# Calibrado con herramientas/calibracion_rag/evaluar.py (qwen3-embedding:0.6b,
# 26 casos + 5 consultas basura, TOP_K=5, 2026-11-15): la basura llega como
# máximo a 0.519 y el acierto más bajo que hay que conservar es 0.537
# (rebaja_aplicada). 0.53 descarta toda la basura sin perder ningún caso. El
# margen es estrecho (~0.01 a cada lado): ampliar el set de basura y de casos
# reales antes de moverlo. OJO: no separa artículos relevantes de irrelevantes
# DENTRO de la normativa (medianas 0.601 vs 0.580); eso lo decide
# marcar_aplica. Recalibrar si cambia el modelo, el troceado o las queries.
UMBRAL_SCORE = 0.53

# Query canónica por tipo de problema (concepto, SIN cifras ni fechas)
CONSULTA_POR_TIPO = {
    "errorConsumo": (
        "consumo atípico y facturación elevada por diferencia de lecturas "
        "del medidor"
    ),
    "descensoConsumo": (
        "diferencia de lecturas atípica que supera el promedio histórico de "
        "consumo del usuario; facturación por promedio histórico de consumos y "
        "retorno a la facturación por diferencia de lecturas después del mes atípico"
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
        "inspección interna para descartar la presencia de fugas no visibles "
        "como factor distorsionante del registro de consumos"
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
        "facturación de conexiones domiciliarias cerradas o inactivas: solo se "
        "facturan las conexiones activas; cierre del servicio o medidor inoperativo"
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
        "diferencia de lecturas atípica que supera en más del 100% al promedio "
        "histórico de consumo del usuario; control de calidad de las "
        "facturaciones basadas en diferencia de lecturas"
    ),
    "medidorReciente": (
        "instalación o cambio de medidor y facturación con el nuevo medidor"
    ),
    "rebajaAplicada": (
        "devolución o compensación de pagos en exceso mediante notas de abono "
        "en las facturaciones futuras como resultado del reclamo"
    ),
    "estadoMedidorInspeccion": (
        "verificación del funcionamiento del medidor en la inspección; medidor "
        "operativo que registra correctamente el consumo"
    ),
    "fugasInspeccionExterna": (
        "la inspección realizada para descartar factores distorsionantes del "
        "registro de consumos no revela la existencia de fugas; facturación "
        "según el promedio histórico de consumos"
    ),
    "estadoConexionInspeccion": (
        "responsabilidad de la empresa prestadora en la operatividad y "
        "mantenimiento de la conexión domiciliaria y la caja del medidor, "
        "verificada en la inspección externa"
    ),
    "inspeccionInternaRealizada": (
        "inspección interna de las instalaciones sanitarias del predio"
    ),
    "inspeccionInternaSinAcceso": (
        "la inspección interna no puede realizarse por causa atribuible al "
        "usuario o titular de la conexión: la empresa prestadora no puede "
        "acceder al predio, la prueba ya no es necesaria y se factura según la "
        "diferencia de lecturas"
    ),
    # Sin la palabra "prórroga": arrastraba al Art. 24 de Reclamos
    # ("Prórroga para resolver"), que no tiene nada que ver.
    "prorrogasCorte": (
        "prohibición de cierre del servicio por falta de pago de los montos y "
        "conceptos reclamados mientras el reclamo está en trámite"
    ),
}


# Los hechos del mes reclamado se rigen por normas distintas según el consumo
# sea atípico o no. Con una sola query, un mes normal (54 m³ vs 52 de promedio)
# traía el régimen de consumo atípico (92.3) y el de medidores instalados por
# primera vez (91 e), y el 91 f) (diferencia de lecturas válida) salía tercero.
CONSULTA_MES_RECLAMADO = {
    True: (
        "diferencia de lecturas atípica que supera en más del 100% al promedio "
        "histórico de consumo del usuario; inspección para descartar factores "
        "distorsionantes y facturación según el promedio histórico de consumos"
    ),
    False: (
        "diferencia de lecturas válida: lectura mensual del medidor con un período "
        "entre lecturas no menor a veintiocho ni mayor a treinta y dos días "
        "calendario para facturar consumos"
    ),
}
TIPOS_SEGUN_ATIPICO = frozenset({"lecturaMesReclamado", "facturacionMesReclamado"})


def _metodo_configurado() -> str:
    try:
        from app.src.infrastructure.config.settings import settings
        return settings.yumi_busqueda_normativa or "indice"
    except Exception:
        return "indice"


def situacion_del_caso(informe) -> dict:
    """Datos del caso que deciden qué normas PUEDEN aplicar:
    - atipico: el consumo del mes reclamado es atípico (True/False) o no se sabe (None);
    - con_medidor: la conexión tiene medidor (facturada por lectura o con tarjeta de lecturas);
    - medidor_reciente: hubo instalación o cambio de medidor."""
    atipico = con_medidor = None
    medidor_reciente = False
    for bloque in getattr(informe, "bloques", None) or []:
        for h in bloque.hechos:
            valor = h.valor or {}
            if h.tipo == "lecturaMesReclamado":
                con_medidor = True
                if valor.get("atipico") is not None:
                    atipico = bool(valor["atipico"]) or bool(atipico)
            elif h.tipo == "facturacionMesReclamado" and str(valor.get("forma", "")).upper() == "MEDIDO":
                con_medidor = True
            elif h.tipo in ("medidorReciente", "errorReinstalacion"):
                medidor_reciente = True
    return {"atipico": atipico, "con_medidor": con_medidor, "medidor_reciente": medidor_reciente}


def premisa_no_cumplida(articulo: dict, situacion: dict | None) -> str | None:
    """Motivo por el que un artículo recuperado NO puede regular el caso (su
    supuesto de hecho no se da), o None. Es determinista: el LLM marcaba el
    93.2 (conexión SIN medidor) en un predio con medidor, y el 92.3 (régimen
    atípico) en un mes normal."""
    if not situacion:
        return None
    numeral = str(articulo.get("numeral") or "")
    article = str(articulo.get("article") or "")
    inicio = " ".join((articulo.get("texto") or "")[:220].lower().split())
    if (situacion.get("atipico") is False and article == "92"
            and numeral in ("92.2", "92.3", "92.4")):
        return "régimen de consumo atípico y el mes reclamado no es atípico"
    if situacion.get("con_medidor") and "sin medidor" in inicio:
        return "conexión sin medidor y el predio tiene medidor"
    if (situacion.get("con_medidor") and not situacion.get("medidor_reciente")
            and ("por primera vez" in inicio or "nuevas conexiones" in inicio)):
        return "instalación del medidor por primera vez y no hubo instalación ni cambio"
    return None


_ARTICULO_CITADO_RE = re.compile(r"\bart(?:[íi]culo|\.)\s*(\d+)", re.IGNORECASE)
_FRASE_CITADA_RE = re.compile(r"[«\"“]([^«»\"“”]{25,})[»\"”]")


def _plano(texto: str) -> str:
    import unicodedata
    sin = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", sin.lower()).split())


def verificar_citas(parrafo: str, problemas: list[ProblemaNormado]) -> list[str]:
    """Problemas de trazabilidad del párrafo (vacío = todo verificado):
    - un artículo citado que no está entre los marcados `aplica`;
    - una frase entre comillas que no aparece literalmente en esos artículos.
    Es determinista: no depende de que el LLM "recuerde" bien la norma."""
    aplicables = [a for p in problemas for a in (p.articulos or []) if a.get("aplica")]
    numeros = {str(a.get("article")) for a in aplicables if a.get("article")}
    textos = " || ".join(_plano(a.get("texto") or "") for a in aplicables)
    errores = []
    for num in dict.fromkeys(_ARTICULO_CITADO_RE.findall(parrafo or "")):
        if num not in numeros:
            errores.append(
                f"cita el artículo {num}, que no está entre los artículos aplicables "
                f"({', '.join(sorted(numeros)) or 'ninguno'})")
    for frase in _FRASE_CITADA_RE.findall(parrafo or ""):
        if _plano(frase) not in textos:
            errores.append(f"la frase entre comillas «{frase[:80]}» no aparece literalmente en la norma")
    return errores


def _cita(article, numeral, norma) -> str:
    """'Art. 93.2 del Reglamento de Calidad de ...'. Con dos reglamentos
    indexados, el número solo es ambiguo (ambos tienen un artículo 14)."""
    ref = f"Art. {numeral or article}"
    return f"{ref} del {norma}" if norma else ref


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

    def __init__(self, qdrant: PuertoBaseVectorial | None, llm_router: LlmRouterService,
                 model: str | None = None, metodo: str | None = None, catalogo=None):
        self.retriever = Retriever(qdrant) if qdrant is not None else None
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT
        # "indice" (base normativa + índice de títulos + BM25) o "vectorial"
        # (Qdrant). Configurable con YUMI_BUSQUEDA_NORMATIVA sin redesplegar.
        self.metodo = (metodo or _metodo_configurado()).strip().lower()
        if self.metodo == "vectorial" and self.retriever is None:
            raise ValueError("La búsqueda vectorial necesita un almacén vectorial (qdrant)")
        self._catalogo = catalogo
        # id(problema) -> IDs de artículos elegidos desde el índice (navegar()).
        self._navegacion: dict[int, list[str]] = {}

    @property
    def catalogo(self):
        if self._catalogo is None:
            from app.src.application.services.normativa.catalogo import catalogo_normativo
            self._catalogo = catalogo_normativo()
        return self._catalogo

    # ------------------------------------------------------------------ #
    # 1) Búsqueda vectorial
    # ------------------------------------------------------------------ #
    @staticmethod
    def construir_query(problema: ProblemaNormado, contexto: str = "", situacion: dict | None = None) -> str:
        """Texto que se vectoriza para buscar los artículos de un problema.
        Separado para que la evaluación (herramientas/calibracion_rag) use
        exactamente la misma query que producción."""
        concepto_general = CONSULTA_POR_TIPO.get(problema.tipo, "")
        if problema.tipo in TIPOS_SEGUN_ATIPICO:
            atipico = (problema.valor or {}).get("atipico")
            if atipico is None and situacion:
                atipico = situacion.get("atipico")
            if atipico is not None:
                concepto_general = CONSULTA_MES_RECLAMADO[bool(atipico)]
        concepto_especifico = _concepto(problema.detalle)
        # El concepto específico va primero (mayor peso semántico); luego el
        # concepto general del grupo, y por último el motivo del reclamo, que
        # aporta el contexto real del caso (p.ej. "fuga reparada") sin el cual
        # no se pueden recuperar los artículos que tratan ese contexto.
        return f"{concepto_especifico}. {concepto_general}. {contexto}".strip(". ")

    def buscar_articulos(self, problema: ProblemaNormado, contexto: str = "",
                         situacion: dict | None = None) -> list[dict]:
        if self.metodo == "indice":
            return self._buscar_por_indice(problema, contexto, situacion)
        query = self.construir_query(problema, contexto, situacion)
        resultados = self.retriever.retrieve(
            query=query,
            top_k=TOP_K,
            collections=COLECCIONES,
        )
        # Qdrant devuelve ordenado por score desc; filtramos por umbral.
        return [r for r in resultados if r.get("score", 0) >= UMBRAL_SCORE]

    # ------------------------------------------------------------------ #
    # 1b) Búsqueda por índice (como un agente de código: índice -> leer)
    # ------------------------------------------------------------------ #
    def navegar(self, problemas: list[ProblemaNormado], contexto: str = "",
                situacion: dict | None = None) -> dict[int, list[str]]:
        """UNA llamada al LLM para todos los hechos: con el índice de títulos
        delante, elige qué artículos leer para cada uno. Guarda el resultado
        para buscar_articulos. Si la llamada falla, los hechos quedan sin
        elección y buscar_articulos se apoya solo en la búsqueda léxica."""
        if self.metodo != "indice" or not problemas:
            return {}
        validos = self.catalogo.ids_articulos()
        estado = []
        if situacion and situacion.get("atipico") is not None:
            estado.append("el consumo del mes reclamado ES atípico" if situacion["atipico"]
                          else "el consumo del mes reclamado NO es atípico")
        if situacion and situacion.get("con_medidor"):
            estado.append("la conexión tiene medidor")
        hechos = "\n".join(f"[{i}] {p.detalle}" for i, p in enumerate(problemas))
        human = (
            f"ÍNDICE DE LOS REGLAMENTOS:\n{self.catalogo.indice()}\n\n"
            + (f"Motivo del reclamo (alegación del usuario): {contexto}\n" if contexto else "")
            + (f"Situación verificada del caso: {'; '.join(estado)}.\n" if estado else "")
            + f"\nHECHOS:\n{hechos}\n\nDevuelve SOLO el JSON."
        )
        try:
            respuesta = constructor_contexto.llamar(
                "fundamentacion_navegacion", self.llm_router, self.model_id, entrada=human,
            )
        except Exception as exc:
            logger.warning("[FUNDAMENTACION] Falló la navegación por índice: %s", exc)
            respuesta = ""
        elegidos = self._parse_navegacion(respuesta or "", len(problemas), validos)
        for i, p in enumerate(problemas):
            self._navegacion[id(p)] = elegidos.get(i, [])
            logger.info("[FUNDAMENTACION] Índice -> %s | %s", self._navegacion[id(p)], p.detalle[:80])
        return {id(p): self._navegacion[id(p)] for p in problemas}

    @staticmethod
    def _parse_navegacion(texto: str, n: int, validos: set[str]) -> dict[int, list[str]]:
        """{"hechos": [{"hecho": 0, "articulos": [...]}]} -> {0: [...]}. Descarta
        IDs que no existen (el modelo no puede inventar artículos) y limita a 3."""
        salida: dict[int, list[str]] = {}
        match = re.search(r"\{.*\}", texto, re.DOTALL)
        try:
            datos = json.loads(match.group()) if match else {}
        except json.JSONDecodeError:
            datos = {}
        entradas = datos.get("hechos") if isinstance(datos, dict) else None
        for pos, e in enumerate(entradas or []):
            if not isinstance(e, dict):
                continue
            try:
                i = int(e.get("hecho", pos))
            except (TypeError, ValueError):
                i = pos
            if not 0 <= i < n:
                continue
            ids = []
            for a in e.get("articulos") or []:
                a = str(a).strip()
                if a in validos and a not in ids:
                    ids.append(a)
            salida[i] = ids[:3]
        return salida

    LEXICOS_POR_HECHO = 3

    def _buscar_por_indice(self, problema: ProblemaNormado, contexto: str,
                           situacion: dict | None) -> list[dict]:
        """Candidatos de un hecho: las unidades de los artículos elegidos desde
        el índice (texto literal, en orden) + las mejores coincidencias léxicas
        de la query del hecho. Misma forma que los resultados de Qdrant."""
        if id(problema) not in self._navegacion:
            self.navegar([problema], contexto, situacion)
        candidatos: list[dict] = []
        vistos: set[str] = set()
        for art_id in self._navegacion.get(id(problema), []):
            for u in self.catalogo.leer(art_id):
                if u.id not in vistos:
                    vistos.add(u.id)
                    candidatos.append(self.catalogo.a_resultado(u, 1.0, "indice"))
        query = self.construir_query(problema, "", situacion)
        lexicos = self.catalogo.buscar_texto(query, k=self.LEXICOS_POR_HECHO + len(vistos))
        maximo = lexicos[0][1] if lexicos else 1.0
        agregados = 0
        for u, s in lexicos:
            if u.id in vistos or agregados >= self.LEXICOS_POR_HECHO:
                continue
            vistos.add(u.id)
            agregados += 1
            candidatos.append(self.catalogo.a_resultado(u, round(s / maximo, 4), "lexica"))
        return candidatos

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
            f"[{_cita(a['payload'].get('article'), a['payload'].get('numeral'), a['payload'].get('norma'))}] "
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
                # ID estable en la base normativa ("RC.91.f"); None si viene de Qdrant.
                "unidad_id": a["payload"].get("unidad_id"),
                "article": a["payload"].get("article"),
                "numeral": a["payload"].get("numeral"),
                "norma": a["payload"].get("norma"),
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

    @staticmethod
    def indices_fijos(pool: list[ProblemaNormado]) -> list[int]:
        """Índices de los hechos que entran SIEMPRE (por regla, sin el LLM).
        Primero los del mes reclamado y después las demás limitaciones: en ese
        orden llegan a la redacción, que empieza por el mes en disputa."""
        return ([i for i, p in enumerate(pool) if p.tipo in HECHOS_MES_RECLAMADO]
                + [i for i, p in enumerate(pool)
                   if p.tipo in SIEMPRE_INCLUIDOS and p.tipo not in HECHOS_MES_RECLAMADO])

    @classmethod
    def hechos_fijos(cls, informe) -> list[ProblemaNormado]:
        """Los hechos que ``seleccionar_determinantes`` incluirá sí o sí. Se
        conocen ANTES de la selección por LLM, así que sus artículos pueden
        buscarse mientras el modelo elige los adicionales."""
        if not cls._medios_determinantes(informe):
            return []
        pool = cls.pool_determinante(informe)
        return [pool[i] for i in cls.indices_fijos(pool)]

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

        fijos = self.indices_fijos(pool)

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
            logger.debug("RESPUESTA LLM seleccion (raw): %s", response_text)
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
        situacion: dict | None = None,
        codreclamo: str | None = None,
    ) -> list[dict]:
        """De los artículos recuperados por RAG, pide al LLM cuáles REGULAN el
        problema y devuelve el payload de artículos con un flag `aplica` por cada
        uno (y `manual=False`). Es la relevancia por artículo que luego el usuario
        puede curar en el front. Los artículos cuya premisa no se cumple en el
        caso (premisa_no_cumplida) quedan con aplica=False sin consultar al LLM."""
        payload = self.articulos_a_payload(articulos_raw)
        for a in payload:
            a["aplica"] = False
            a["manual"] = False
        candidatos = []
        for i, a in enumerate(payload):
            motivo_descarte = premisa_no_cumplida(a, situacion)
            if motivo_descarte:
                logger.info("[FUNDAMENTACION] Descartado %s: %s",
                            _cita(a.get("article"), a.get("numeral"), None), motivo_descarte)
            else:
                candidatos.append(i)
        if not candidatos:
            return payload

        listado = "\n".join(
            f"[{j}] {_cita(payload[i].get('article'), payload[i].get('numeral'), payload[i].get('norma'))}: "
            f"{payload[i]['texto']}"
            for j, i in enumerate(candidatos)
        )
        hechos_caso = []
        if situacion and situacion.get("atipico") is not None:
            hechos_caso.append("el consumo del mes reclamado ES atípico" if situacion["atipico"]
                               else "el consumo del mes reclamado NO es atípico")
        if situacion and situacion.get("con_medidor"):
            hechos_caso.append("la conexión tiene medidor")
        human = (
            f"Hallazgo: {problema.detalle}\n"
            f"Tipo de reclamo: {clasificacion or 'no especificado'}\n"
            + (f"Motivo (contexto): {contexto}\n" if contexto else "")
            + (f"Situación verificada del caso: {'; '.join(hechos_caso)}. Un artículo "
               "cuyo supuesto de hecho no se da en el caso NO aplica.\n" if hechos_caso else "")
            + f"\nArtículos:\n{listado}\n\n"
            "Devuelve SOLO el JSON con los índices de los artículos que aplican."
        )
        response_text = constructor_contexto.llamar(
            "fundamentacion_aplicabilidad", self.llm_router, self.model_id, entrada=human,
            codreclamo=codreclamo,
        )
        logger.debug("RESPUESTA LLM marcar_aplica (raw): %s", response_text)
        for j in self._parse_indices(response_text or "", len(candidatos)):
            payload[candidatos[j]]["aplica"] = True
        return payload

    def redactar_parrafo(
        self,
        problemas: list[ProblemaNormado],
        motivo: str = "",
        clasificacion: str = "",
        codreclamo: str | None = None,
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
                    f"    [{_cita(a.get('article'), a.get('numeral'), a.get('norma'))}] {a.get('texto', '')}"
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
            codreclamo=codreclamo,
        )
        texto = (texto or "").strip()

        # Trazabilidad: toda cita debe salir del texto que se le entregó. Si
        # cita un artículo que no estaba entre los aplicables o "cita" una
        # frase que no existe en la norma, se le pide corregir UNA vez.
        problemas_citas = verificar_citas(texto, problemas)
        if problemas_citas:
            logger.warning("[FUNDAMENTACION] Citas no verificadas: %s", problemas_citas)
            correccion = (
                human + "\n\nTu redacción anterior fue:\n" + texto
                + "\n\nCORRIGE estos problemas de cita (cita SOLO los artículos aplicables "
                "listados y, si usas comillas, copia el texto literal):\n- "
                + "\n- ".join(problemas_citas)
            )
            try:
                corregido = (constructor_contexto.llamar(
                    "fundamentacion_parrafo", self.llm_router, self.model_id, entrada=correccion,
                    codreclamo=codreclamo,
                ) or "").strip()
            except Exception as exc:
                logger.warning("[FUNDAMENTACION] Falló la corrección de citas: %s", exc)
                corregido = ""
            if corregido and len(verificar_citas(corregido, problemas)) < len(problemas_citas):
                texto = corregido
        return texto
