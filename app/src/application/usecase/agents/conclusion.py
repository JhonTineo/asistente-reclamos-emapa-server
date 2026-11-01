"""Agente de conclusión del informe de atención.

Evalúa cada OBJETIVO de investigación (derivado del motivo del reclamo) contra
los HALLAZGOS de los medios probatorios y decide el veredicto con una REGLA
EXPLÍCITA (puerta lógica), no con criterio libre del LLM:

    FUNDADO   ⇔ algún objetivo DETERMINANTE resultó "procede_correccion"
    INFUNDADO ⇔ ningún objetivo DETERMINANTE resultó "procede_correccion"

Los objetivos no_evaluable se conservan sin bloquear el veredicto. Una
evaluación inválida o un fallo del proveedor siguen siendo errores técnicos.

"procede_correccion" cubre tanto un error de la empresa (medidor/medición) como
una refacturación que procede sin culpa de la empresa (p.ej. fuga no visible ya
reparada → refacturar por promedio histórico, Art. 92.3/88.3 SUNASS).

El LLM solo realiza la tarea acotada de evaluar cada objetivo contra los
hallazgos; la decisión final la toma el código, de forma determinista y trazable.
"""

import re
import json
import logging
from dataclasses import asdict
from datetime import datetime

from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.core.model.criterios_especialista import (
    CriterioEvaluacion, obtener_criterios, render_criterios,
)
from app.src.core.model.informe_atencion import (
    InformeAtencion, MotivoEvaluacion, ObjetivoInvestigacion,
)

logger = logging.getLogger("agent.conclusion")

RESULTADOS_VALIDOS = {"procede_correccion", "sin_correccion", "no_evaluable"}


class RespuestaEvaluacionInvalida(ValueError):
    def __init__(self, codigo: str, descripcion: str, objetivos: list[int] | None = None):
        super().__init__(descripcion)
        self.codigo = codigo
        self.descripcion = descripcion
        self.objetivos = objetivos or []


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
        self._iniciar_nueva_evaluacion(informe)
        if not informe.objetivos:
            return self._dejar_sin_decision(
                informe, "requiere_revision", "SIN_OBJETIVOS", [],
                "No se definieron objetivos de investigación.",
                "Definir los objetivos antes de evaluar el reclamo.",
            )

        determinantes = [o for o in informe.objetivos if o.determinante]
        if not determinantes:
            return self._dejar_sin_decision(
                informe, "requiere_revision", "SIN_OBJETIVOS_DETERMINANTES",
                [o.id for o in informe.objetivos],
                "Hay objetivos, pero ninguno está marcado como determinante.",
                "Revisar y marcar los objetivos determinantes.",
            )

        try:
            evaluaciones = self._evaluar_objetivos(
                informe, self._hallazgos_por_medio(informe),
            )
        except RespuestaEvaluacionInvalida as exc:
            return self._dejar_sin_decision(
                informe, "error_evaluacion", exc.codigo, exc.objetivos,
                exc.descripcion, "Reintentar la evaluación o revisar el proveedor.",
            )
        except Exception as exc:
            logger.exception("[CONCLUSION] Falló el proveedor de evaluación")
            return self._dejar_sin_decision(
                informe, "error_evaluacion", "ERROR_PROVEEDOR",
                [o.id for o in determinantes],
                f"Falló la comunicación con el proveedor de evaluación: {exc}",
                "Reintentar cuando el proveedor esté disponible.",
            )

        for obj in determinantes:
            obj.resultado = evaluaciones[obj.id]["resultado"]
            obj.evidencia = evaluaciones[obj.id]["evidencia"]

        # no_evaluable conserva su resultado/evidencia para futuras notas,
        # pero no veta una decisión ni se convierte en sin_correccion.
        con_correccion = [o for o in determinantes if o.resultado == "procede_correccion"]
        veredicto = "FUNDADO" if con_correccion else "INFUNDADO"
        informe.veredicto = veredicto
        informe.estado_evaluacion = "completada"
        informe.motivos_evaluacion = []
        informe.mensaje_evaluacion = "Veredicto y conclusión generados con la evaluación disponible."
        informe.origen_decision = "automatica"
        informe.conclusion = self._redactar_conclusion(
            informe, veredicto, determinantes, con_correccion,
        )
        return veredicto

    @staticmethod
    def _iniciar_nueva_evaluacion(informe: InformeAtencion) -> None:
        if informe.veredicto or informe.conclusion or informe.propuesta_conciliacion or informe.resolucion:
            informe.historial_decisiones.append({
                "fecha": datetime.now().isoformat(),
                "veredicto": informe.veredicto,
                "conclusion": informe.conclusion,
                "estado_evaluacion": informe.estado_evaluacion,
                "origen_decision": informe.origen_decision,
                "propuesta_conciliacion": (
                    asdict(informe.propuesta_conciliacion)
                    if informe.propuesta_conciliacion else None
                ),
                "resolucion": informe.resolucion,
            })
        informe.veredicto = None
        informe.conclusion = None
        informe.propuesta_conciliacion = None
        informe.resolucion = None
        informe.estado_evaluacion = "pendiente"
        informe.motivos_evaluacion = []
        informe.mensaje_evaluacion = None
        informe.origen_decision = None
        for objetivo in informe.objetivos:
            objetivo.resultado = None
            objetivo.evidencia = None

    @staticmethod
    def _dejar_sin_decision(
        informe: InformeAtencion, estado: str, codigo: str,
        objetivos: list[int], descripcion: str, accion: str,
    ) -> None:
        informe.estado_evaluacion = estado
        informe.veredicto = None
        informe.conclusion = None
        informe.mensaje_evaluacion = descripcion
        informe.motivos_evaluacion = [MotivoEvaluacion(
            codigo=codigo,
            objetivos_afectados=objetivos,
            descripcion=descripcion,
            accion_necesaria=accion,
        )]
        return None

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
        # Solo se evalúan los objetivos DETERMINANTES: son los únicos que la
        # puerta lógica mira para decidir el veredicto. El resultado de los
        # objetivos de contexto no se usa en ningún lado (ni en la puerta, ni en
        # la redacción, ni en el response), así que evaluarlos es trabajo perdido.
        determinantes = [o for o in informe.objetivos if o.determinante]
        if not determinantes:
            logger.info(
                "[CONCLUSION] Sin objetivos determinantes; no se evalúa "
                "(requiere revisión)"
            )
            return {}

        todos_los_hallazgos = (
            "\n".join(hallazgos_por_medio.values()) or "(sin hallazgos registrados)"
        )
        # Las inspecciones interna/externa comparten contexto complementario.
        # Sin medio asignado se reciben todos los hallazgos.
        bloques_objetivo = []
        for o in determinantes:
            etiqueta = f"{o.id}. {o.descripcion}" + (
                f" [medios: {', '.join(o.medios_relacionados)}]" if o.medio else ""
            )
            hallazgos_obj = (
                "\n".join(hallazgos_por_medio.get(
                    medio, f"[{medio}] (el medio aún no fue analizado)",
                ) for medio in o.medios_relacionados)
                if o.medio else todos_los_hallazgos
            )
            bloques_objetivo.append(
                f"{etiqueta}\nHallazgos de los medios relacionados con este objetivo:\n{hallazgos_obj}"
            )
        objetivos_texto = "\n\n".join(bloques_objetivo)

        system = (
            "Eres un analista de reclamos de EMAPA. Evalúas cada objetivo de la "
            "investigación contra LOS HALLAZGOS QUE SE LISTAN DEBAJO DE ESE MISMO "
            "OBJETIVO (no contra los de otros objetivos).\n"
            "La pregunta de fondo es: según los hallazgos de sus medios, ¿CORRESPONDE "
            "CORREGIR la facturación a favor del usuario respecto de ese objetivo?\n"
            "Clasifica cada objetivo en uno de estos resultados, según estos "
            "criterios de especialista:\n"
            f"{render_criterios(self.criterios)}\n"
            "Básate ÚNICAMENTE en los hallazgos listados debajo de cada objetivo. "
            "NUNCA uses hallazgos que no estén listados para el objetivo. "
            "Las inspecciones interna y externa son complementarias: una inspección "
            "externa no acredita que se revisó el interior del predio. Distingue una "
            "visita sin acceso de una inspección interna realizada. No inventes.\n"
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
        return self._parse_evaluaciones(response_text or "", {o.id for o in determinantes})

    @staticmethod
    def _parse_evaluaciones(texto: str, ids_esperados: set[int]) -> dict[int, dict]:
        """Valida forma, cobertura, ids, resultados y evidencia obligatoria."""
        if not texto.strip():
            raise RespuestaEvaluacionInvalida(
                "RESPUESTA_VACIA", "El proveedor devolvió una respuesta vacía.",
                sorted(ids_esperados),
            )
        match = re.search(r"\[.*\]", texto, re.DOTALL)
        if not match:
            raise RespuestaEvaluacionInvalida(
                "JSON_INVALIDO", "La respuesta no contiene una lista JSON válida.",
                sorted(ids_esperados),
            )
        try:
            crudos = json.loads(match.group())
        except json.JSONDecodeError as e:
            raise RespuestaEvaluacionInvalida(
                "JSON_INVALIDO", f"La respuesta JSON es inválida: {e}",
                sorted(ids_esperados),
            ) from e
        if not isinstance(crudos, list):
            raise RespuestaEvaluacionInvalida(
                "FORMATO_INVALIDO", "La evaluación debe ser una lista JSON.",
                sorted(ids_esperados),
            )

        evaluaciones: dict[int, dict] = {}
        for item in crudos:
            if not isinstance(item, dict) or "id" not in item:
                raise RespuestaEvaluacionInvalida(
                    "ITEM_INVALIDO", "Hay una evaluación sin objeto o identificador.",
                    sorted(ids_esperados),
                )
            try:
                oid = int(item["id"])
            except (TypeError, ValueError):
                raise RespuestaEvaluacionInvalida(
                    "IDENTIFICADOR_INVALIDO", "Hay un identificador de objetivo inválido.",
                    sorted(ids_esperados),
                )
            if oid not in ids_esperados:
                raise RespuestaEvaluacionInvalida(
                    "IDENTIFICADOR_DESCONOCIDO", f"El objetivo {oid} no era esperado.", [oid],
                )
            if oid in evaluaciones:
                raise RespuestaEvaluacionInvalida(
                    "IDENTIFICADOR_DUPLICADO", f"El objetivo {oid} aparece duplicado.", [oid],
                )
            evidencia = (str(item.get("evidencia") or "")).strip()
            resultado = item.get("resultado")
            if resultado not in RESULTADOS_VALIDOS:
                raise RespuestaEvaluacionInvalida(
                    "RESULTADO_INVALIDO", f"Resultado inválido para el objetivo {oid}.", [oid],
                )
            if resultado in {"procede_correccion", "sin_correccion"} and not evidencia:
                raise RespuestaEvaluacionInvalida(
                    "EVIDENCIA_OBLIGATORIA",
                    f"El objetivo {oid} afirma un resultado sin sustento.", [oid],
                )
            evaluaciones[oid] = {
                "resultado": resultado,
                "evidencia": evidencia or None,
            }
        faltantes = sorted(ids_esperados - set(evaluaciones))
        if faltantes:
            raise RespuestaEvaluacionInvalida(
                "OBJETIVOS_OMITIDOS", "La respuesta omitió objetivos determinantes.", faltantes,
            )
        return evaluaciones

    # ------------------------------------------------------------------ #
    # Redacción de la conclusión (LLM, coherente con la puerta lógica)
    # ------------------------------------------------------------------ #
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

        # La base normativa YA NO se reconstruye por-problema: se consume el
        # párrafo de fundamentación normativa ya generado (paso de fundamentación).
        # Puede estar vacío: en ese caso la conclusión se apoya solo en los hechos.
        norma_aplicable = (informe.fundamentacion_normativa or "").strip()
        hay_norma = bool(norma_aplicable)

        meses_reclamados = _formatear_meses_reclamados(informe)

        # La fórmula distingue los hechos acreditados de una evaluación parcial.
        # Un INFUNDADO con no_evaluable no certifica que la facturación sea correcta.
        if veredicto == "FUNDADO":
            formula = (
                "«En consecuencia, toda vez que [hecho decisivo verificado con su "
                "cifra, p.ej. la fuga no visible fue reparada], corresponde [lo que "
                "manda la norma, p.ej. refacturar los meses reclamados por el "
                "promedio histórico], por lo tanto se declara FUNDADO»"
            )
        elif any(o.resultado == "no_evaluable" for o in determinantes):
            formula = (
                "«En consecuencia, con la información disponible [hechos evaluados "
                "y alcance de la evaluación], no se acreditó un motivo de corrección "
                "en los objetivos determinantes, por lo tanto se declara INFUNDADO». "
                "No afirmes que toda la facturación es correcta ni que fue por "
                "diferencia de lecturas si no hay evidencia que lo confirme"
            )
        else:
            formula = (
                f"«En consecuencia, toda vez que [hecho verificado concreto que "
                f"sustenta el INFUNDADO; usa la evidencia de las verificaciones "
                f"determinantes — p.ej. 'el usuario tuvo fuga visible en un inodoro' "
                f"o 'la facturación del mes reclamado corresponde a lectura real del "
                f"medidor sin error atribuible a la empresa'], se procedió a la "
                f"facturación por diferencias de lectura del reclamo del mes de "
                f"{meses_reclamados}, por lo tanto se declara INFUNDADO»"
            )

        # Cita de la norma: condicional. Si la búsqueda vectorial halló un
        # artículo pertinente, se cita; si no, la conclusión se apoya solo en los
        # hechos y los criterios, sin citar ni inventar artículos (el veredicto NO
        # cambia por esto: lo fijó la puerta lógica).
        if hay_norma:
            regla_norma = (
                "- Como sustento normativo, apóyate en la FUNDAMENTACIÓN NORMATIVA "
                "ya establecida (abajo) y sé coherente con ella: cita el "
                "artículo/numeral que ahí figure y úsalo tal cual; NO inventes otros "
                "ni cifras que no estén ahí.\n"
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
            "- Los objetivos no_evaluable no bloquean el veredicto, pero tampoco "
            "acreditan hechos ni la corrección de un cobro. No los presentes como "
            "verificaciones satisfactorias. Si todos son no_evaluable, explica "
            "que la decisión se basa en que no se acreditó una causa de corrección "
            "con la información disponible.\n"
            + regla_norma +
            "Responde SOLO con el párrafo de conclusión, sin encabezados."
        )
        human = (
            f"Veredicto ya determinado (NO modificar): {veredicto}\n\n"
            f"Meses reclamados: {meses_reclamados}\n\n"
            f"Motivo del reclamo:\n{informe.motivo or 'no especificado'}\n\n"
            f"Verificaciones determinantes y su resultado:\n{determinantes_texto}\n\n"
            + (f"Fundamentación normativa ya establecida:\n{norma_aplicable}\n\n"
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
        if any(o.resultado == "no_evaluable" for o in determinantes):
            return (
                "En consecuencia, con la información disponible no se acreditó "
                "una causa de corrección en los objetivos determinantes, por lo "
                "tanto se declara INFUNDADO. La evaluación incompleta de algunos "
                "objetivos no acredita que la facturación sea correcta."
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
