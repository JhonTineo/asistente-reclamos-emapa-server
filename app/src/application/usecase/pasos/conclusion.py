"""Paso de conclusión del informe de atención.

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

from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.core.model.criterios_especialista import (
    CriterioEvaluacion, obtener_criterios, render_criterios,
)
from app.src.core.model.informe_atencion import (
    InformeAtencion, MotivoEvaluacion, ObjetivoInvestigacion, ProblemaNormado,
)
from app.src.application.services.pre_proces.constataciones import (
    HECHOS_MES_RECLAMADO, LIMITACIONES,
)
from app.src.application.usecase.pasos.dictamen import PasoDictamen

logger = logging.getLogger("paso.conclusion")


def _modo_configurado() -> str:
    from app.src.infrastructure.config.settings import settings
    return settings.yumi_veredicto or "dictamen"

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


def _historial_consumos(informe: InformeAtencion) -> str | None:
    """Rango de consumos de la tarjeta de lecturas SIN el mes reclamado. Es lo
    que responde a «mis consumos son de unos 35 m³» (252629: el historial va de
    40 a 66 m³) y no está en ningún hecho seleccionado."""
    reclamados = {h.periodo for b in informe.bloques for h in b.hechos
                  if h.tipo in HECHOS_MES_RECLAMADO and h.periodo}
    for bloque in informe.bloques:
        if bloque.medio_id != "tarjeta_lectura":
            continue
        consumos = []
        for r in (bloque.entidad or {}).get("registros") or []:
            try:
                periodo = f"{int(r.get('anio')):04d}-{int(r.get('mes')):02d}"
                consumo = float(r.get("consumo"))
            except (TypeError, ValueError):
                continue
            if periodo not in reclamados:
                consumos.append(consumo)
        if len(consumos) >= 3:
            fmt = lambda v: f"{v:g}"
            return (f"Historial de consumos de la tarjeta de lecturas ({len(consumos)} meses, sin el "
                    f"mes reclamado): entre {fmt(min(consumos))} y {fmt(max(consumos))} m³.")
    return None


class PasoConclusion:

    def __init__(self, llm_router: LlmRouterService, model: str | None = None,
                 criterios: list[CriterioEvaluacion] | None = None,
                 modo: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT
        # Criterios de especialista que guían la clasificación de cada objetivo
        # (solo en el modo "objetivos").
        self.criterios = criterios if criterios is not None else obtener_criterios()
        # "dictamen" (criterios de las skills contra los hechos) u "objetivos"
        # (método anterior). Se elige con YUMI_VEREDICTO para poder volver al
        # método anterior en producción sin redesplegar.
        self.modo = (modo or _modo_configurado()).strip().lower()

    # ------------------------------------------------------------------ #
    # Metodo principal que se expone con la api /conclusion
    # ------------------------------------------------------------------ #
    def concluir_y_asignar(self, informe: InformeAtencion) -> str | None:
        """Calcula veredicto + conclusión sobre el informe (in-place).
        Devuelve el veredicto ("FUNDADO"/"INFUNDADO") o None si no hay decisión."""
        if self.modo == "dictamen":
            return self._concluir_con_dictamen(informe)
        return self._concluir_con_objetivos(informe)

    # ------------------------------------------------------------------ #
    # Modo dictamen
    # ------------------------------------------------------------------ #
    def _concluir_con_dictamen(self, informe: InformeAtencion) -> str | None:
        self._iniciar_nueva_evaluacion(informe)
        try:
            dictamen = PasoDictamen(self.llm_router, self.model_id).dictaminar(informe)
        except Exception as exc:
            logger.exception("[CONCLUSION] Falló el proveedor durante el dictamen")
            return self._dejar_sin_decision(
                informe, "error_evaluacion", "ERROR_PROVEEDOR", [],
                f"Falló la comunicación con el proveedor de evaluación: {exc}",
                "Reintentar cuando el proveedor esté disponible.",
            )
        informe.dictamen = dictamen.a_dict()

        if dictamen.veredicto is None:
            informe.estado_evaluacion = dictamen.estado
            informe.veredicto = None
            informe.conclusion = None
            informe.motivos_evaluacion = dictamen.motivos
            informe.mensaje_evaluacion = (
                dictamen.motivos[0].descripcion if dictamen.motivos else "El caso requiere revisión."
            )
            return None

        informe.veredicto = dictamen.veredicto
        informe.estado_evaluacion = "completada"
        informe.motivos_evaluacion = dictamen.motivos     # advertencias, si las hay
        informe.mensaje_evaluacion = (
            "Veredicto del dictamen con advertencias: revisar los motivos."
            if dictamen.motivos else "Veredicto y conclusión generados a partir del dictamen."
        )
        informe.origen_decision = "automatica"
        verificaciones, a_favor = self._verificaciones_del_dictamen(dictamen)
        informe.conclusion = self._redactar_conclusion(
            informe, dictamen.veredicto, verificaciones, a_favor,
        )
        return dictamen.veredicto

    @staticmethod
    def _verificaciones_del_dictamen(dictamen) -> tuple[list[ObjetivoInvestigacion], list[ObjetivoInvestigacion]]:
        """Presenta los factores del dictamen como las "verificaciones
        determinantes" que ya sabe usar la redacción de la conclusión:
        - un criterio que aplica a favor del usuario → procede_correccion;
        - uno que aplica a favor de la empresa → sin_correccion;
        - uno decisivo que no se pudo determinar → no_evaluable (limitación)."""
        verificaciones: list[ObjetivoInvestigacion] = []
        for factor in dictamen.factores:
            if factor.aplica == "aplica" and factor.favorece in ("usuario", "empresa"):
                resultado = "procede_correccion" if factor.favorece == "usuario" else "sin_correccion"
            elif factor.aplica == "no_determinable" and factor.fuerza == "decisivo":
                resultado = "no_evaluable"
            else:
                continue
            verificaciones.append(ObjetivoInvestigacion(
                id=len(verificaciones) + 1,
                descripcion=f"{factor.criterio} · {factor.nombre}",
                determinante=True, resultado=resultado,
                evidencia=factor.explicacion or None,
            ))
        a_favor = [v for v in verificaciones if v.resultado == "procede_correccion"]
        return verificaciones, a_favor

    # ------------------------------------------------------------------ #
    # Modo objetivos (método anterior)
    # ------------------------------------------------------------------ #
    def _concluir_con_objetivos(self, informe: InformeAtencion) -> str | None:
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
        informe.dictamen = None
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
                lineas.append(f"    · Problema: {p.detalle}{accion}")
            # Los hechos verificados por reglas (lectura del mes reclamado,
            # medidor operativo, inspección sin acceso...) son la evidencia más
            # fiable: tienen prioridad sobre la redacción del resumen.
            for c in bloque.constataciones:
                lineas.append(f"    · Hecho verificado: {c.detalle}")
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

        # Lo fijo está en skills/pasos/evaluacion_objetivos.md; los criterios de
        # especialista se añaden aquí porque son configurables por instancia.
        instrucciones = (
            "Clasifica cada objetivo en uno de estos resultados, según estos "
            "criterios de especialista:\n"
            f"{render_criterios(self.criterios)}"
        )
        human = (
            f"Motivo del reclamo:\n{informe.motivo or 'no especificado'}\n\n"
            f"Objetivos de la investigación (cada uno con sus hallazgos relevantes):\n"
            f"{objetivos_texto}\n\n"
            "Devuelve SOLO el JSON."
        )

        response_text = constructor_contexto.llamar(
            "evaluacion_objetivos", self.llm_router, self.model_id,
            entrada=human, instrucciones=instrucciones, codreclamo=informe.reclamo,
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
    @staticmethod
    def _hechos_para_conclusion(informe: InformeAtencion) -> list[ProblemaNormado]:
        """Hechos que la conclusión debe tener a la vista, en orden de bloque y
        sin duplicados: los que sustentan la fundamentación (seleccionados), las
        limitaciones de la verificación, los hechos del mes reclamado y los del
        informe técnico operacional (descartan o confirman el aire en la red y
        las interrupciones, que el dictamen sí evalúa con VPA-01/INT-01)."""
        hechos: list[ProblemaNormado] = []
        for bloque in informe.bloques:
            for h in bloque.hechos:
                if (h.seleccionado or h.tipo in LIMITACIONES
                        or h.tipo in HECHOS_MES_RECLAMADO
                        or bloque.medio_id == "tecnico_operacional"):
                    if all(h is not otro for otro in hechos):
                        hechos.append(h)
        return hechos

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

        # Los hechos completos (no solo la evidencia de 12 palabras): así la
        # redacción no rellena huecos generalizando un hecho más allá de su alcance.
        hechos = self._hechos_para_conclusion(informe)
        lineas_hechos = [f"- {h.detalle}" for h in hechos]
        historial = _historial_consumos(informe)
        if historial:
            lineas_hechos.append(f"- {historial}")
        # Pruebas faltantes (hechos del caso, no de un medio): son el hecho
        # decisivo de un FUNDADO por PRU-01 y no están en ningún bloque. Sin
        # ellas, el 252396 se fundamentó con «15 m³ supera el promedio».
        faltantes = [h.get("detalle") for h in ((informe.dictamen or {}).get("hechos_caso") or [])
                     if isinstance(h, dict) and h.get("tipo") == "pruebaFaltante" and h.get("detalle")]
        lineas_hechos += [f"- {d}" for d in faltantes]
        hechos_texto = "\n".join(lineas_hechos)
        limitaciones = [h for h in hechos if h.tipo in LIMITACIONES]

        # La base normativa YA NO se reconstruye por-problema: se consume el
        # párrafo de fundamentación normativa ya generado (paso de fundamentación).
        # Puede estar vacío: en ese caso la conclusión se apoya solo en los hechos.
        norma_aplicable = (informe.fundamentacion_normativa or "").strip()
        hay_norma = bool(norma_aplicable)

        meses_reclamados = _formatear_meses_reclamados(informe)

        # La fórmula distingue los hechos acreditados de una evaluación parcial.
        # Un INFUNDADO con no_evaluable no certifica que la facturación sea correcta.
        # Estructura: lo verificado → lo que de ahí se sigue → el veredicto. Los
        # corchetes describen qué va en cada hueco SIN cifras ni fechas de
        # ejemplo (el modelo las copia como si fueran del caso). Se evita «toda
        # vez que [hecho], se procedió a la facturación…»: quedaba circular (se
        # facturó por lectura, luego se facturó por lectura) y no respondía al
        # reclamo.
        if veredicto == "FUNDADO":
            formula = (
                "«En consecuencia, se ha verificado que [el hecho decisivo, con su "
                "cifra o su fecha]; por ello corresponde [lo que manda la norma "
                "sobre la facturación de los meses reclamados], y el reclamo se "
                "declara FUNDADO.» El hecho decisivo es el de la verificación con "
                "resultado procede_correccion (su evidencia), NO el consumo del mes "
                "si este es normal. No escribas que corresponde mantener la "
                "facturación ni que es correcta: eso contradice el FUNDADO"
            )
            if faltantes:
                formula += (
                    ". Aquí el hecho decisivo es la PRUEBA FALTANTE: nómbrala (qué "
                    "medio no se actuó y por qué era exigible)"
                )
        elif any(o.resultado == "no_evaluable" for o in determinantes):
            formula = (
                "«En consecuencia, se ha verificado que [los hechos comprobados, con "
                "sus cifras]; sin embargo, [la limitación concreta de la "
                "verificación, tal como figura en los hechos]. Al no haberse "
                "acreditado un error atribuible a la empresa en la facturación de "
                f"{meses_reclamados}, el reclamo se declara INFUNDADO.» "
                "Nombra la limitación tal como figura en los hechos; no la "
                "sustituyas por una fórmula genérica como «con la información "
                "disponible». No afirmes que toda la facturación es correcta ni que "
                "fue por diferencia de lecturas si no hay un hecho que lo confirme"
            )
        else:
            formula = (
                "«En consecuencia, se ha verificado que [los dos o tres hechos que "
                "responden a lo que el usuario reclama, con sus cifras: el consumo "
                "del mes reclamado frente al promedio, la validez de la lectura y el "
                "resultado de las inspecciones, según los que existan], sin que se "
                "haya encontrado [la causa que el usuario alega u otra que "
                "justifique corregir el recibo]; por ello, la facturación de "
                f"{meses_reclamados} se mantiene y el reclamo se declara INFUNDADO.»"
            )

        # Cita de la norma: condicional. Si la búsqueda vectorial halló un
        # artículo pertinente, se cita; si no, la conclusión se apoya solo en los
        # hechos y los criterios, sin citar ni inventar artículos (el veredicto NO
        # cambia por esto: lo fijó la puerta lógica).
        if hay_norma:
            regla_norma = (
                "- Sé coherente con la FUNDAMENTACIÓN NORMATIVA ya establecida "
                "(abajo), que precede a esta conclusión en el informe. NO repitas su "
                "contenido ni vuelvas a explicar el artículo: como mucho, menciona "
                "una vez el número del artículo que ahí figura. NO cites otros "
                "artículos ni cifras que no estén en los hechos.\n"
            )
        else:
            regla_norma = (
                "- NO se halló un artículo pertinente: concluye apoyándote SOLO en los "
                "hechos verificados; NO cites ni inventes artículos.\n"
            )

        # Lo fijo está en skills/pasos/conclusion_redaccion.md; aquí solo lo que
        # depende del caso: la fórmula del veredicto, la limitación y la norma.
        instrucciones = (
            "- El párrafo DEBE empezar con «En consecuencia,» y seguir esta "
            f"estructura, sustituyendo cada corchete por los datos del caso: {formula}\n"
            "- Resume en una frase lo comprobado; no repitas uno por uno los datos "
            "de la fundamentación normativa. No uses «toda vez que» ni «se procedió "
            "a la facturación». Lo que el usuario afirma en el motivo es una "
            "alegación: no la presentes como un hecho.\n"
            "- Si el usuario alega un consumo habitual y hay historial de consumos "
            "entre los hechos, contrástalo con ese historial (con sus cifras). Si "
            "hay hechos del informe técnico operacional que descartan o confirman "
            "la causa alegada (aire en la red, interrupciones), menciónalos.\n"
            + ("- Hay una LIMITACIÓN de la verificación entre los hechos: menciónala "
               "expresamente en la conclusión.\n" if limitaciones else "")
            + regla_norma
        )
        human = (
            f"Veredicto ya determinado (NO modificar): {veredicto}\n\n"
            f"Meses reclamados: {meses_reclamados}\n\n"
            f"Motivo del reclamo:\n{informe.motivo or 'no especificado'}\n\n"
            f"Verificaciones determinantes y su resultado:\n{determinantes_texto}\n\n"
            + (f"Hechos verificados del caso:\n{hechos_texto}\n\n" if hechos_texto else "")
            + (f"Fundamentación normativa ya establecida:\n{norma_aplicable}\n\n"
               if hay_norma else "")
            + "Redacta la conclusión."
        )

        try:
            texto = constructor_contexto.llamar(
                "conclusion_redaccion", self.llm_router, self.model_id,
                entrada=human, instrucciones=instrucciones, codreclamo=informe.reclamo,
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
