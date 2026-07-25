"""Agente de conclusión del informe de atención.

Evalúa cada OBJETIVO de investigación (derivado del motivo del reclamo) contra
los HALLAZGOS de los medios probatorios y decide el veredicto con una REGLA
EXPLÍCITA (puerta lógica), no con criterio libre del LLM:

    FUNDADO  ⇔  algún objetivo DETERMINANTE resultó "procede_correccion"
    INFUNDADO en caso contrario

"procede_correccion" cubre tanto un error de la empresa (medidor/medición) como
una refacturación que procede sin culpa de la empresa (p.ej. fuga no visible ya
reparada → refacturar por promedio histórico, Art. 92.3/88.3 SUNASS).

El LLM solo realiza la tarea acotada de evaluar cada objetivo contra los
hallazgos; la decisión final la toma el código, de forma determinista y trazable.
"""

import re
import json
import logging

from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.core.model.criterios_especialista import (
    CriterioEvaluacion, obtener_criterios, render_criterios,
)
from app.src.core.model.informe_atencion import InformeAtencion, ObjetivoInvestigacion

logger = logging.getLogger("agent.conclusion")

RESULTADOS_VALIDOS = {"procede_correccion", "sin_correccion", "no_evaluable"}


def _formatear_meses_reclamados(informe: InformeAtencion) -> str:
    """Meses reclamados en prosa para la conclusión. El campo `mesanio` viene
    crudo (p.ej. 'SETIEMBRE-2022') y se normaliza a 'setiembre 2022'. Fallback:
    'el mes en reclamo'."""
    crudo = informe.datos_reclamo.meses_reclamados if informe.datos_reclamo else None
    return (crudo or "el mes en reclamo").replace("-", " ").lower()


class ConclusionAgent:

    def __init__(self, llm_router: LlmRouterService, model: str | None = None,
                 criterios: list[CriterioEvaluacion] | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT
        # Criterios de especialista que guían la clasificación de cada objetivo.
        self.criterios = criterios if criterios is not None else obtener_criterios()

    # ------------------------------------------------------------------ #
    # Metodo principal que se expone con la api /conclusion
    # ------------------------------------------------------------------ #
    def concluir_y_asignar(self, informe: InformeAtencion) -> str | None:
        """Evalúa objetivos vs hallazgos, fija el resultado de cada objetivo y
        calcula veredicto + conclusión sobre el informe (in-place).
        Devuelve el veredicto ("FUNDADO"/"INFUNDADO") o None si no hay objetivos."""
        if not informe.objetivos:
            logger.warning("[CONCLUSION] Informe sin objetivos; no se decide con regla")
            informe.veredicto = None
            informe.conclusion = (
                "No se definieron objetivos de investigación, por lo que el "
                "veredicto no se determina automáticamente."
            )
            return informe.veredicto

        hallazgos_por_medio = self._hallazgos_por_medio(informe) # podriamos 
        evaluaciones = self._evaluar_objetivos(informe, hallazgos_por_medio)

        # Vuelca la evaluación (por id de objetivo) sobre cada objetivo.
        for obj in informe.objetivos:
            ev = evaluaciones.get(obj.id, {})
            resultado = ev.get("resultado")
            obj.resultado = resultado if resultado in RESULTADOS_VALIDOS else "no_evaluable"
            obj.evidencia = ev.get("evidencia")

        # --- Puerta lógica (determinista) --------------------------------
        # FUNDADO ⇔ Si algún objetivo DETERMINANTE resultó "procede_correccion", es
        # decir, corresponde corregir la facturación a favor del usuario. Esto
        # abarca tanto un error de la empresa (medidor/medición) como una
        # refacturación procedente sin culpa de la empresa 
        # (p.ej. fuga no visible ya reparada → refacturar por promedio histórico).
        determinantes = [o for o in informe.objetivos if o.determinante]
        con_correccion = [o for o in determinantes if o.resultado == "procede_correccion"]
        veredicto = "FUNDADO" if con_correccion else "INFUNDADO"

        informe.veredicto = veredicto
        # El veredicto lo fija la puerta lógica (arriba); el LLM SOLO redacta el
        # párrafo que lo fundamenta (no puede cambiarlo). Si el LLM falla, se usa
        # la plantilla determinista como respaldo.
        informe.conclusion = self._redactar_conclusion(informe, veredicto, determinantes, con_correccion)

        logger.info(
            "[CONCLUSION] veredicto=%s | determinantes=%d | con_correccion=%d",
            veredicto, len(determinantes), len(con_correccion),
        )
        return veredicto

    # ------------------------------------------------------------------ #
    # Evaluación de objetivos con LLM
    # ------------------------------------------------------------------ #
    @staticmethod
    def _hallazgos_por_medio(informe: InformeAtencion) -> dict[str, str]:
        """medio_id -> texto de hallazgos de ESE medio (resumen + problemas).
        Se mantiene separado por medio para que al evaluar un objetivo que
        apunta a un medio concreto el LLM reciba SOLO lo relevante"""
        por_medio: dict[str, str] = {}
        for bloque in informe.bloques:
            lineas = [f"[{bloque.medio_id}] {bloque.medio_nombre}: {bloque.resumen}"]
            for p in bloque.problemas:
                accion = f" · acción: {p.accion}" if p.accion else ""
                lineas.append(f"    · {p.detalle}{accion}")
            por_medio[bloque.medio_id] = "\n".join(lineas)
        return por_medio

    def _evaluar_objetivos(
        self, informe: InformeAtencion, hallazgos_por_medio: dict[str, str],
    ) -> dict[int, dict]:
        todos_los_hallazgos = (
            "\n".join(hallazgos_por_medio.values()) or "(sin hallazgos registrados)"
        )
        # Cada objetivo se lista junto a SOLO los hallazgos de su medio (si lo
        # tiene asignado); si no tiene medio asignado, recibe todos los
        # hallazgos como contexto general. .
        bloques_objetivo = []
        for o in informe.objetivos:
            etiqueta = f"{o.id}. {o.descripcion}" + (f" [medio: {o.medio}]" if o.medio else "")
            hallazgos_obj = (
                hallazgos_por_medio.get(o.medio, "(el medio aún no fue analizado)")
                if o.medio else todos_los_hallazgos
            )
            bloques_objetivo.append(
                f"{etiqueta}\nHallazgos del medio asignado a este objetivo:\n{hallazgos_obj}"
            )
        objetivos_texto = "\n\n".join(bloques_objetivo)

        system = (
            "Eres un analista de reclamos de EMAPA. Evalúas cada objetivo de la "
            "investigación contra LOS HALLAZGOS QUE SE LISTAN DEBAJO DE ESE MISMO "
            "OBJETIVO (no contra los de otros objetivos).\n"
            "La pregunta de fondo es: según los hallazgos de su medio, ¿CORRESPONDE "
            "CORREGIR la facturación a favor del usuario respecto de ese objetivo?\n"
            "Clasifica cada objetivo en uno de estos resultados, según estos "
            "criterios de especialista:\n"
            f"{render_criterios(self.criterios)}\n"
            "Básate ÚNICAMENTE en los hallazgos listados debajo de cada objetivo. "
            "NUNCA uses como evidencia un hallazgo de un medio distinto al asignado "
            "al objetivo. No inventes.\n"
            "Responde SOLO con un JSON: una lista de objetos con las claves "
            "\"id\" (número del objetivo), \"resultado\" y \"evidencia\".\n"
            "\"evidencia\" debe ser una frase MUY BREVE (máximo 12 palabras) citando el "
            "dato puntual que sustenta el resultado, NUNCA el resumen completo del medio. "
            "Ejemplo de evidencia válida: \"medidor con número incorrecto en 12/2025\". "
            "Si no hay evidencia puntual, usa \"\"."
        )
        human = (
            f"Motivo del reclamo:\n{informe.motivo or 'no especificado'}\n\n"
            f"Objetivos de la investigación (cada uno con sus hallazgos relevantes):\n"
            f"{objetivos_texto}\n\n"
            "Devuelve SOLO el JSON."
        )

        logger.debug("[PROMPT conclusion][SYSTEM]\n%s", system)
        logger.debug("[PROMPT conclusion][HUMAN]\n%s", human)

        response_text = self.llm_router.generar_json(
            mensajes=[
                MensajeLLM(rol="system", contenido=system),
                MensajeLLM(rol="user", contenido=human)
            ],
            modelo_id=self.model_id
        )
        return self._parse_evaluaciones(response_text or "")

    @staticmethod
    def _parse_evaluaciones(texto: str) -> dict[int, dict]:
        """Extrae la lista JSON de la respuesta del LLM y la convierte en un dict"""
        match = re.search(r"\[.*\]", texto, re.DOTALL)
        if not match:
            logger.warning("[CONCLUSION] El LLM no devolvió lista JSON: %s", texto[:200])
            return {}
        try:
            crudos = json.loads(match.group())
        except json.JSONDecodeError as e:
            logger.warning("[CONCLUSION] JSON inválido del LLM: %s | %s", e, texto[:200])
            return {}

        evaluaciones: dict[int, dict] = {}
        for item in crudos:
            if not isinstance(item, dict) or "id" not in item:
                continue
            try:
                oid = int(item["id"])
            except (TypeError, ValueError):
                continue
            evidencia = (str(item.get("evidencia") or "")).strip()
            evaluaciones[oid] = {
                "resultado": item.get("resultado"),
                "evidencia": evidencia or None,
            }
        return evaluaciones

    # ------------------------------------------------------------------ #
    # Redacción de la conclusión (LLM, coherente con la puerta lógica)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _norma_aplicable(informe: InformeAtencion, medios: set[str] | None = None) -> str:
        """Texto de la norma APLICABLE de los medios (determinantes): SOLO los
        problemas cuya fundamentación halló un artículo pertinente (con
        `base_legal` asignada tras el guardarraíl de abstención). Devuelve cadena
        VACÍA si no se halló ninguno; en ese caso la conclusión se apoya solo en
        los hechos y los criterios, sin citar normas ni inventarlas."""
        lineas: list[str] = []
        for bloque in informe.bloques:
            if medios is not None and bloque.medio_id not in medios:
                continue
            for p in bloque.problemas:
                if not p.base_legal:
                    continue
                partes = [f"- {p.detalle} → {p.accion or 'corrección'} ({p.base_legal})"]
                for art in (p.articulos or []):
                    texto = (art.get("texto") or "").strip()
                    if texto:
                        num = art.get("numeral") or art.get("article") or ""
                        partes.append(f"  Art. {num}: {texto}")
                lineas.append("\n".join(partes))
        return "\n".join(lineas)

    def _redactar_conclusion(
        self,
        informe: InformeAtencion,
        veredicto: str,
        determinantes: list[ObjetivoInvestigacion],
        con_correccion: list[ObjetivoInvestigacion],
    ) -> str:
        """Pide al LLM el párrafo de conclusión. El veredicto YA está decidido
        por la puerta lógica; el modelo solo lo fundamenta (no puede cambiarlo).
        Ante cualquier fallo, cae a la plantilla determinista."""
        # Solo los objetivos DETERMINANTES guían la redacción; los demás son
        # contexto de soporte y solo inflarían el prompt sin cambiar la conclusión.
        determinantes_texto = "\n".join(
            f"- {o.descripcion} [resultado={o.resultado or 'no_evaluable'}"
            + (f", evidencia: {o.evidencia}" if o.evidencia else "")
            + "]"
            for o in determinantes
        ) or "(sin objetivos determinantes)"

        # Norma aplicable de los medios determinantes (solo artículos pertinentes).
        # Puede estar vacía: en ese caso la conclusión se apoya solo en los hechos.
        medios_det = {o.medio for o in determinantes if o.medio}
        norma_aplicable = self._norma_aplicable(informe, medios_det or None)
        hay_norma = bool(norma_aplicable)

        meses_reclamados = _formatear_meses_reclamados(informe)

        # La fórmula del informe real depende del veredicto: FUNDADO narra el hecho
        # decisivo y la refacturación que procede; INFUNDADO afirma que la
        # facturación fue correcta por diferencia de lecturas.
        if veredicto == "FUNDADO":
            formula = (
                "«En consecuencia, toda vez que [hecho decisivo verificado con su "
                "cifra, p.ej. la fuga no visible fue reparada], corresponde [lo que "
                "manda la norma, p.ej. refacturar los meses reclamados por el "
                "promedio histórico], por lo tanto se declara FUNDADO»"
            )
        else:
            formula = (
                f"«En consecuencia, la facturación emitida en el mes en reclamo "
                f"({meses_reclamados}) es correcta, de acuerdo a diferencias de "
                "lecturas, ya que [el medidor registraba consumo/estaba operativo y "
                "no se halló problema atribuible a la empresa], por lo tanto se "
                "declara INFUNDADO»"
            )

        # Cita de la norma: condicional. Si la búsqueda vectorial halló un
        # artículo pertinente, se cita; si no, la conclusión se apoya solo en los
        # hechos y los criterios, sin citar ni inventar artículos (el veredicto NO
        # cambia por esto: lo fijó la puerta lógica).
        if hay_norma:
            regla_norma = (
                "- Como sustento normativo, cita el artículo/numeral incluido en "
                "«Norma aplicable» y úsalo tal cual; NO inventes otros ni cifras que "
                "no estén ahí.\n"
            )
        else:
            regla_norma = (
                "- NO se halló un artículo pertinente: concluye apoyándote SOLO en los "
                "hechos verificados; NO cites ni inventes artículos.\n"
            )

        system = (
            "Eres un analista de reclamos de EMAPA que redacta la CONCLUSIÓN de un "
            "informe de atención, según el Reglamento de Calidad SUNASS.\n"
            "IMPORTANTE: el veredicto ya fue determinado por una regla y NO puedes "
            "cambiarlo; tu tarea es redactar el párrafo que lo fundamenta.\n"
            "Reglas de redacción:\n"
            "- Escribe UN SOLO párrafo formal y conciso (sin viñetas ni JSON) y "
            "SIN título ni encabezado.\n"
            "- El párrafo DEBE empezar con «En consecuencia,» y seguir EXACTAMENTE "
            f"esta estructura del informe real: {formula}.\n"
            "- Usa lenguaje llano y directo; NO uses expresiones vagas como «dentro "
            "de los parámetros establecidos». Nombra el hecho concreto.\n"
            + regla_norma +
            "Responde SOLO con el párrafo de conclusión, sin encabezados."
        )
        human = (
            f"Veredicto ya determinado (NO modificar): {veredicto}\n\n"
            f"Meses reclamados: {meses_reclamados}\n\n"
            f"Motivo del reclamo:\n{informe.motivo or 'no especificado'}\n\n"
            f"Verificaciones determinantes y su resultado:\n{determinantes_texto}\n\n"
            + (f"Norma aplicable (artículos pertinentes hallados):\n{norma_aplicable}\n\n"
               if hay_norma else "")
            + "Redacta la conclusión."
        )

        logger.debug("[PROMPT conclusion_redaccion][SYSTEM]\n%s", system)
        logger.debug("[PROMPT conclusion_redaccion][HUMAN]\n%s", human)

        try:
            texto = self.llm_router.generar_texto(
                mensajes=[
                    MensajeLLM(rol="system", contenido=system),
                    MensajeLLM(rol="user", contenido=human)
                ],
                modelo_id=self.model_id
            )
            texto = (texto or "").strip()
        except Exception as e:
            logger.warning("[CONCLUSION] Falló la redacción con LLM: %s", e)
            texto = ""

        if not texto:
            logger.warning("[CONCLUSION] Redacción LLM vacía; uso plantilla de respaldo")
            return self._construir_conclusion(veredicto, determinantes, con_correccion)
        return texto

    # ------------------------------------------------------------------ #
    # Texto de conclusión (determinista, respaldo si falla el LLM)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _construir_conclusion(
        veredicto: str,
        determinantes: list[ObjetivoInvestigacion],
        con_correccion: list[ObjetivoInvestigacion],
    ) -> str:
        if veredicto == "FUNDADO":
            motivos = "; ".join(
                f"{o.descripcion}: {o.evidencia}" if o.evidencia else o.descripcion
                for o in con_correccion
            )
            return (
                "En consecuencia, el reclamo se declara FUNDADO, por cuanto la "
                f"investigación determinó que corresponde corregir la facturación a "
                f"favor del usuario: {motivos}."
            )
        if determinantes:
            detalle = "; ".join(o.descripcion for o in determinantes)
            return (
                "En consecuencia, el reclamo se declara INFUNDADO, por cuanto no "
                f"corresponde corregir la facturación en las verificaciones "
                f"determinantes ({detalle})."
            )
        return (
            "En consecuencia, el reclamo se declara INFUNDADO, por cuanto no "
            "corresponde corregir la facturación según la investigación."
        )
