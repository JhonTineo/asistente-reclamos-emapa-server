"""Agente que define los objetivos de investigación de un reclamo.

A partir del motivo (lo que reclama el cliente) y la clasificación, genera una
lista de objetivos concretos y verificables. Cada objetivo se marca como
`determinante` cuando su resultado decide el veredicto FUNDADO/INFUNDADO.

Los objetivos se generan al buscar el reclamo y guían toda la investigación.
"""

import json
import re
import logging

from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.core.model.informe_atencion import ObjetivoInvestigacion

logger = logging.getLogger("agent.objetivos")

# Medios probatorios disponibles y qué información tiene cada uno. Se usa para
# que el LLM asocie cada objetivo al medio que puede responderlo, y para que
# entienda de antemano el alcance real de cada medio (evita objetivos que
# ningún medio puede verificar).
MEDIOS = {
    "tarjeta_lectura": (
        "Lectura del medidor de cada mes, consumos atipícos, problemas en el medidor"
    ),
    "inspeccion_interna": (
        "Inspección del interior del predio, fugas despues del medidor, estado de las instalaciones sanitarias, y observaciones del inspector."
    ),
    "inspeccion_externa": (
        "Inspección de la conexión externa, estado del medidor y de la caja, fugas antes del medidor, y observaciones del inspector."
    ),
    "corte_reapertura": (
        "Historial de cortes del servicio por deuda, reaperturas, "
        "prórrogas, reclamos previos y observaciones para citar."
    ),
    "record_facturacion": (
        "Facturación de cada mes, tipo de facturación (promedio o lectura), cambios de facturación y observaciones."
    ),
    "saldo_detalle": (
        "Pagos por mes: cobro indebido por servicio no prestado, cobro de mora y meses pendientes de pago."
    ),
}


class ObjetivosAgent:

    def __init__(self, llm_router: LlmRouterService, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT

    def generar(self, motivo: str, clasificacion: str = "") -> list[ObjetivoInvestigacion]:
        if not motivo or not motivo.strip():
            logger.warning("[OBJETIVOS] Motivo vacío; no se generan objetivos")
            return []

        medios_texto = "\n".join(f"- {medio}: {desc}" for medio, desc in MEDIOS.items())
        system = (
            "Eres un analista de reclamos de EMAPA. A partir del motivo del reclamo "
            "defines los OBJETIVOS de investigación: qué verificar en los medios "
            "probatorios para determinar si el reclamo procede (FUNDADO) o no (INFUNDADO).\n\n"
            "Medios probatorios disponibles y qué información tiene cada uno:\n"
            f"{medios_texto}\n\n"
            "MÉTODO:\n"
            "1. Primero identifica la PREGUNTA DECISIVA: dado el motivo, ¿qué hecho, por "
            "sí solo, haría FUNDADO este reclamo? (p.ej. en un reclamo por fuga: '¿la fuga "
            "no visible fue reparada?', que se ve en la caída del consumo al promedio).\n"
            "2. Deriva de 2 a 4 OBJETIVOS concretos y verificables. NO generes uno por "
            "cada medio: solo los que realmente importan para este reclamo.\n"
            "3. Formula cada objetivo como PREGUNTA NEUTRAL verificable (no como una "
            "afirmación que dé por hecho el resultado), para no sesgar el análisis.\n\n"
            "DETERMINANTE:\n"
            "- Marca determinante=true SOLO el objetivo (uno; a lo sumo dos) cuyo "
            "resultado POR SÍ SOLO cambia el veredicto FUNDADO↔INFUNDADO (el que responde "
            "la pregunta decisiva).\n"
            "- Los objetivos de contexto o soporte van con determinante=false, aunque "
            "sean útiles.\n"
            "- En \"porque_determinante\" explica en una frase por qué ese objetivo "
            "decide (o no) el veredicto.\n\n"
            "Ejemplo (reclamo por fuga no visible):\n"
            "[{\"descripcion\": \"¿El consumo de los meses reclamados retorna al promedio "
            "histórico en un mes posterior (fuga reparada)?\", \"medio\": \"tarjeta_lectura\", "
            "\"determinante\": true, \"porque_determinante\": \"si la fuga se reparó procede "
            "refacturar por promedio (FUNDADO); si persiste, se factura por diferencia "
            "(INFUNDADO)\"}, {\"descripcion\": \"¿La inspección halló fugas o problemas en "
            "el medidor?\", \"medio\": \"inspeccion_externa\", \"determinante\": false, "
            "\"porque_determinante\": \"aporta contexto del estado del predio, pero no "
            "decide por sí solo\"}]\n\n"
            "Responde SOLO con el JSON (lista de objetos con las claves \"descripcion\", "
            "\"medio\", \"determinante\", \"porque_determinante\"), sin texto adicional."
        )
        human = (
            f"Motivo del reclamo:\n{motivo}\n\n"
            f"Clasificación: {clasificacion or 'no especificada'}\n\n"
            "Devuelve SOLO el JSON (lista de objetivos)."
        )

        logger.debug("[PROMPT objetivos][SYSTEM]\n%s", system)
        logger.debug("[PROMPT objetivos][HUMAN]\n%s", human)

        response_text = self.llm_router.generar_json(
            mensajes=[
                MensajeLLM(rol="system", contenido=system),
                MensajeLLM(rol="user", contenido=human)
            ],
            modelo_id=self.model_id
        )

        objetivos = self._parse(response_text or "")
        n_det = sum(1 for o in objetivos if o.determinante)
        logger.info(
            "[OBJETIVOS] %d objetivo(s) generados | determinantes=%d", len(objetivos), n_det,
        )
        # El gate del veredicto (conclusion.py) es sensible al nº de determinantes:
        # marcar muchos como determinante lo vuelve frágil (falsos FUNDADO). El
        # prompt pide 1-2; si el modelo devuelve más, se avisa para vigilarlo.
        if n_det > 2:
            logger.warning(
                "[OBJETIVOS] %d objetivos marcados como determinante (>2); el prompt pide "
                "1-2. Revisar la calidad de los objetivos para este motivo.", n_det,
            )
        return objetivos

    @staticmethod
    def _parse(texto: str) -> list[ObjetivoInvestigacion]:
        # El LLM puede devolver un array [...] o un objeto {key: [...]} 
        # (response_format=json_object fuerza {})
        texto = texto.strip()
        try:
            parsed = json.loads(texto)
        except json.JSONDecodeError:
            # Fallback: buscar array con regex
            match = re.search(r"\[.*\]", texto, re.DOTALL)
            if not match:
                logger.warning("[OBJETIVOS] El LLM no devolvió JSON válido: %s", texto[:200])
                return []
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError as e:
                logger.warning("[OBJETIVOS] JSON inválido: %s | %s", e, texto[:200])
                return []

        # Si es un dict, buscar la primera lista dentro de sus valores
        if isinstance(parsed, dict):
            crudos = None
            for v in parsed.values():
                if isinstance(v, list):
                    crudos = v
                    break
            if crudos is None:
                # Es un solo objetivo como objeto suelto
                crudos = [parsed]
        elif isinstance(parsed, list):
            crudos = parsed
        else:
            logger.warning("[OBJETIVOS] JSON no es lista ni dict: %s", texto[:200])
            return []

        objetivos: list[ObjetivoInvestigacion] = []
        for i, o in enumerate(crudos, start=1):
            if not isinstance(o, dict) or not o.get("descripcion"):
                continue
            medio = o.get("medio")
            objetivos.append(
                ObjetivoInvestigacion(
                    id=i,
                    descripcion=str(o["descripcion"]).strip(),
                    medio=medio if medio in MEDIOS else None,
                    determinante=bool(o.get("determinante", False)),
                )
            )
        return objetivos
