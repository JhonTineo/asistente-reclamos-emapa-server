"""Paso que define los objetivos de investigación de un reclamo.

A partir del motivo (lo que reclama el cliente) y la clasificación, genera una
lista de objetivos concretos y verificables. Cada objetivo se marca como
`determinante` cuando su resultado decide el veredicto FUNDADO/INFUNDADO.

Los objetivos se generan al buscar el reclamo y guían toda la investigación.
"""

import json
import re
import logging

from app.src.application.services.contexto.constructor import constructor_contexto
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
from app.src.core.model.informe_atencion import ObjetivoInvestigacion

logger = logging.getLogger("paso.objetivos")

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
    "tecnico_operacional": (
        "Informe del área operacional sobre el sector del predio: horario de abastecimiento "
        "(continuo o restringido), interrupciones o desabastecimiento en el periodo reclamado, "
        "existencia y estado de las válvulas de purga de aire. Úsalo cuando el reclamo alegue "
        "falta de servicio, horario restringido, cortes de agua o aire en la tubería: la "
        "empresa debe acreditar con él que el medidor registró solo agua."
    ),
}


class PasoObjetivos:

    def __init__(self, llm_router: LlmRouterService, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT

    def generar(self, motivo: str, clasificacion: str = "",
                codreclamo: str | None = None) -> list[ObjetivoInvestigacion]:
        if not motivo or not motivo.strip():
            logger.warning("[OBJETIVOS] Motivo vacío; no se generan objetivos")
            return []

        medios_texto = "\n".join(f"- {medio}: {desc}" for medio, desc in MEDIOS.items())
        # Lo fijo (método, determinante, ejemplos) está en skills/pasos/objetivos.md;
        # el código solo añade la lista de medios, que también usa para validar.
        instrucciones = (
            "Medios probatorios disponibles y qué información tiene cada uno:\n" + medios_texto
        )
        human = (
            f"Motivo del reclamo:\n{motivo}\n\n"
            f"Clasificación: {clasificacion or 'no especificada'}\n\n"
            "Devuelve SOLO el JSON (lista de objetivos)."
        )

        response_text = constructor_contexto.llamar(
            "objetivos", self.llm_router, self.model_id,
            entrada=human, instrucciones=instrucciones, codreclamo=codreclamo,
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
