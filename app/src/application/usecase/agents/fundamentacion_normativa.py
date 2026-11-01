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
    # Tipos que salían SIN consulta canónica (la búsqueda quedaba sin el
    # concepto general del grupo): hallazgos de inspección, record y cortes.
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
    # Tipos de hallazgo de fuga y consumo añadidos al flujo de selección de
    # problemas determinantes: misma idea que "fugas" (la norma de reclamos
    # regula la inspección como prueba, no la facturación por fuga).
    "descensoConsumo": (
        "medios de prueba del reclamo por consumo: histórico de lecturas y de "
        "facturación para declarar el reclamo fundado o infundado"
    ),
    "fugaNoVisible": (
        "inspección interna y externa como medio de prueba en el reclamo por "
        "consumo elevado cuando se detecta una fuga, y acta de inspección"
    ),
    "fugaVisible": (
        "inspección interna y externa como medio de prueba en el reclamo por "
        "consumo elevado cuando se detecta una fuga, y acta de inspección"
    ),
    "fugaNoDetectada": (
        "inspección interna y externa como medio de prueba cuando no se detecta "
        "una fuga: acta de inspección y declaración del reclamo"
    ),
    "fugaSospechada": (
        "inspección y verificación como medios de prueba ante una sospecha de "
        "fuga en el reclamo por consumo elevado"
    ),
    "fugaReferida": (
        "inspección interna y externa como medio de prueba ante una fuga "
        "referida por el usuario en el reclamo por consumo elevado"
    ),
    "contradiccionFuga": (
        "acta de inspección como medio de prueba y valoración de las "
        "observaciones de la inspección en el reclamo por consumo"
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
            "No infieras una fuga, su visibilidad o una reparación a partir de un "
            "descenso de consumo. Una reparación solo puede afirmarse si otra "
            "fuente la acredita expresamente.\n\n"
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
        return {medio for o in informe.objetivos if o.determinante
                for medio in o.medios_relacionados}

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
            idxs = [i for medio in o.medios_relacionados
                    for i in idxs_por_medio.get(medio, [])]
            if idxs:
                lineas += [f"  [{i}] {pool[i].detalle}" for i in idxs]
            else:
                lineas.append("  (sin problemas registrados en este medio)")
            grupos.append("\n".join(lineas))

        system = (
            "Eres un analista de reclamos de EMAPA. Debes seleccionar, de la lista "
            "de PROBLEMAS agrupados por objetivo, los 1 a 3 problemas con relación "
            "DIRECTA con el motivo del reclamo y que, según la normativa SUNASS, "
            "deciden si corresponde corregir la facturación.\n"
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

    def buscar_y_marcar(
        self,
        problema: ProblemaNormado,
        clasificacion: str = "",
        contexto: str = "",
    ) -> list[dict]:
        """Búsqueda ESCALONADA + relevancia por artículo (`marcar_aplica`).

        Se recuperan los artículos de la norma de atención de reclamos y el LLM
        marca cuáles regulan el hallazgo. Si NINGUNO aplica, se pasa a la
        siguiente norma (calidad) y se repite. Devuelve los artículos de todas las
        normas consultadas (cada uno con su `coleccion` y `norma_corta`): el
        frontend ve qué se evaluó en la norma prioritaria y con cuál se argumentó.
        Si ninguna norma tiene artículos por encima del umbral, devuelve []."""
        todos: list[dict] = []
        nivel = 0
        while nivel < len(self.buscador.fuentes):
            crudos = self.buscar_articulos(problema, contexto, nivel=nivel)
            if not crudos:
                break
            marcados = self.marcar_aplica(problema, crudos, clasificacion, contexto)
            todos.extend(marcados)
            if any(a.get("aplica") for a in marcados):
                break
            logger.info(
                "[%s] ningún artículo regula el hallazgo; se escala a la siguiente norma",
                crudos[0]["fuente"].coleccion,
            )
            nivel = self.buscador.nivel_de(crudos) + 1
        return todos

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
            f"[{i}] Art. {a['numeral'] or a['article']}"
            + (f" del {a['norma_corta']}" if a.get("norma_corta") else "")
            + f": {a['texto']}"
            for i, a in enumerate(payload)
        )
        system = (
            "Eres un analista normativo de EMAPA. De la lista de ARTÍCULOS de la "
            "normativa SUNASS (cada uno indica de qué reglamento es), decide cuáles "
            "REGULAN DIRECTAMENTE el hallazgo indicado (no basta que sean del mismo "
            "tema). Un artículo que no trata la situación del hallazgo NO aplica.\n"
            "Responde SOLO con un JSON: una lista de enteros con los índices [n] de "
            "los artículos que SÍ aplican (p. ej. [0, 2]). Si ninguno aplica, [ ]."
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
        response_text = self.llm_router.generar_json(
            mensajes=[
                MensajeLLM(rol="system", contenido=system),
                MensajeLLM(rol="user", contenido=human),
            ],
            modelo_id=self.model_id,
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
                    f"    [Art. {a.get('numeral') or a.get('article')}"
                    + (f" del {a['norma_corta']}" if a.get("norma_corta") else "")
                    + f"] {a.get('texto', '')}"
                    for a in aplicables
                )
            else:
                arts = "    (sin artículos aplicables)"
            secciones.append(f"- Hallazgo: {problema.detalle}\n  Artículos aplicables:\n{arts}")
        hallazgos_texto = "\n\n".join(secciones)

        system = (
            "Eres un analista normativo de EMAPA. Redactas el PÁRRAFO de "
            "fundamentación normativa de un informe de atención, según la "
            "normativa SUNASS (Reglamento de Reclamos o Reglamento de Calidad, "
            "según indique cada artículo).\n"
            "Reglas:\n"
            "- Escribe UN SOLO párrafo formal, CONCRETO y sin relleno (sin viñetas "
            "ni JSON, sin título).\n"
            "- Nombra el hecho concreto y cita el/los artículo(s) recuperado(s) que "
            "REGULAN ese hecho (por su numeral y el reglamento del que son); puedes "
            "citar más de uno si ambos aplican. Di qué corresponde facturar según la "
            "norma.\n"
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
