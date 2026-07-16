"""Agente de conclusión del informe de atención.

Evalúa cada OBJETIVO de investigación (derivado del motivo del reclamo) contra
los HALLAZGOS de los medios probatorios y decide el veredicto con una REGLA
EXPLÍCITA (puerta lógica), no con criterio libre del LLM:

    FUNDADO  ⇔  algún objetivo DETERMINANTE resultó "problema_empresa"
    INFUNDADO en caso contrario

El LLM solo realiza la tarea acotada de evaluar cada objetivo contra los
hallazgos; la decisión final la toma el código, de forma determinista y trazable.
"""

import re
import json
import logging

from langchain_core.messages import SystemMessage, HumanMessage

from app.src.application.adapters.llm import get_llm, log_uso_llm
from app.src.core.model.informe_atencion import InformeAtencion, ObjetivoInvestigacion

logger = logging.getLogger("agent.conclusion")

RESULTADOS_VALIDOS = {"problema_empresa", "sin_problema", "no_evaluable"}

# Tope defensivo de la evidencia (por si el LLM ignora la instrucción de
# brevedad y copia el resumen completo del medio como "evidencia").
_MAX_CHARS_EVIDENCIA = 100


class ConclusionAgent:

    def __init__(self, model: str | None = None):
        self.llm = get_llm(model=model)

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def concluir(self, informe: InformeAtencion) -> str | None:
        """Evalúa objetivos vs hallazgos, fija el resultado de cada objetivo y
        calcula veredicto + conclusión sobre el informe in-place.
        Devuelve el veredicto ("FUNDADO"/"INFUNDADO") o None si no hay objetivos."""
        if not informe.objetivos:
            logger.warning("[CONCLUSION] Informe sin objetivos; no se decide con regla")
            informe.veredicto = None
            informe.conclusion = (
                "No se definieron objetivos de investigación, por lo que el "
                "veredicto no se determina automáticamente."
            )
            return informe.veredicto

        hallazgos = self._resumir_hallazgos(informe)
        evaluaciones = self._evaluar_objetivos(informe, hallazgos)

        # Vuelca la evaluación (por id de objetivo) sobre cada objetivo.
        for obj in informe.objetivos:
            ev = evaluaciones.get(obj.id, {})
            resultado = ev.get("resultado")
            obj.resultado = resultado if resultado in RESULTADOS_VALIDOS else "no_evaluable"
            obj.evidencia = ev.get("evidencia")

        # --- Puerta lógica (determinista) --------------------------------
        determinantes = [o for o in informe.objetivos if o.determinante]
        con_problema = [o for o in determinantes if o.resultado == "problema_empresa"]
        veredicto = "FUNDADO" if con_problema else "INFUNDADO"

        informe.veredicto = veredicto
        informe.conclusion = self._construir_conclusion(veredicto, determinantes, con_problema)

        logger.info(
            "[CONCLUSION] veredicto=%s | determinantes=%d | con_problema_empresa=%d",
            veredicto, len(determinantes), len(con_problema),
        )
        return veredicto

    def concluir_y_asignar(self, informe: InformeAtencion) -> str | None:
        """Compatibilidad: ejecuta la conclusión (escribe informe.conclusion y
        informe.veredicto) y devuelve el veredicto."""
        return self.concluir(informe)

    # ------------------------------------------------------------------ #
    # Evaluación de objetivos (LLM, tarea acotada)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resumir_hallazgos(informe: InformeAtencion) -> str:
        lineas: list[str] = []
        for bloque in informe.bloques:
            lineas.append(f"[{bloque.medio_id}] {bloque.medio_nombre}: {bloque.resumen}")
            for p in bloque.problemas:
                responsable = p.responsable or "no_determinable"
                lineas.append(f"    · {p.detalle} (responsabilidad: {responsable})")
        return "\n".join(lineas) if lineas else "(sin hallazgos registrados)"

    def _evaluar_objetivos(self, informe: InformeAtencion, hallazgos: str) -> dict[int, dict]:
        objetivos_texto = "\n".join(
            f"{o.id}. {o.descripcion}" + (f" [medio: {o.medio}]" if o.medio else "")
            for o in informe.objetivos
        )

        system = (
            "Eres un analista de reclamos de EMAPA. Evalúas cada objetivo de la "
            "investigación contra los hallazgos de los medios probatorios.\n"
            "Para cada objetivo responde uno de estos resultados:\n"
            "- \"problema_empresa\": los hallazgos muestran un problema atribuible a "
            "la EMPRESA relacionado con el objetivo (p.ej. error de medición, medidor "
            "defectuoso, lectura mal registrada).\n"
            "- \"sin_problema\": no se halló tal problema (todo correcto, o el problema "
            "es responsabilidad del cliente).\n"
            "- \"no_evaluable\": los hallazgos no permiten evaluar el objetivo.\n"
            "Básate ÚNICAMENTE en los hallazgos proporcionados. No inventes.\n"
            "Responde SOLO con un JSON: una lista de objetos con las claves "
            "\"id\" (número del objetivo), \"resultado\" y \"evidencia\".\n"
            "\"evidencia\" debe ser una frase MUY BREVE (máximo 12 palabras) citando el "
            "dato puntual que sustenta el resultado, NUNCA el resumen completo del medio. "
            "Ejemplo de evidencia válida: \"medidor con número incorrecto en 12/2025\". "
            "Si no hay evidencia puntual, usa \"\"."
        )
        human = (
            f"Motivo del reclamo:\n{informe.motivo or 'no especificado'}\n\n"
            f"Objetivos de la investigación:\n{objetivos_texto}\n\n"
            f"Hallazgos de la investigación:\n{hallazgos}\n\n"
            "Devuelve SOLO el JSON."
        )

        logger.debug("[PROMPT conclusion][SYSTEM]\n%s", system)
        logger.debug("[PROMPT conclusion][HUMAN]\n%s", human)

        response = self.llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=human),
        ])
        log_uso_llm(logger, "conclusion", response)
        return self._parse_evaluaciones(response.content or "")

    @staticmethod
    def _parse_evaluaciones(texto: str) -> dict[int, dict]:
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
            if len(evidencia) > _MAX_CHARS_EVIDENCIA:
                evidencia = evidencia[:_MAX_CHARS_EVIDENCIA].rstrip() + "…"
            evaluaciones[oid] = {
                "resultado": item.get("resultado"),
                "evidencia": evidencia or None,
            }
        return evaluaciones

    # ------------------------------------------------------------------ #
    # Texto de conclusión (determinista, coherente con la puerta lógica)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _construir_conclusion(
        veredicto: str,
        determinantes: list[ObjetivoInvestigacion],
        con_problema: list[ObjetivoInvestigacion],
    ) -> str:
        if veredicto == "FUNDADO":
            motivos = "; ".join(
                f"{o.descripcion}: {o.evidencia}" if o.evidencia else o.descripcion
                for o in con_problema
            )
            return (
                "el reclamo se declara FUNDADO, por cuanto la investigación halló al "
                f"menos un problema atribuible a la empresa: {motivos}."
            )
        if determinantes:
            detalle = "; ".join(o.descripcion for o in determinantes)
            return (
                "el reclamo se declara INFUNDADO, por cuanto no se hallaron problemas "
                f"atribuibles a la empresa en las verificaciones determinantes ({detalle})."
            )
        return (
            "el reclamo se declara INFUNDADO, por cuanto no se hallaron problemas "
            "atribuibles a la empresa en la investigación."
        )
