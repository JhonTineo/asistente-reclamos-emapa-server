"""Normaliza los problemas detectados en el preprocesamiento a una lista
uniforme de ProblemaNormado, independiente del medio probatorio.

Por ahora soporta la tarjeta de lecturas; los demás medios se agregan como
nuevas ramas del dispatcher.
"""

import logging

from app.src.core.model.targeta_lecturas import TargetaLecturas
from app.src.core.model.saldo_detalle import SaldoDetalle
from app.src.core.model.informe_atencion import ProblemaNormado

logger = logging.getLogger("services.problemas_normalizer")

# Medios que ya tienen detección de problemas implementada.
MEDIOS_SOPORTADOS = {"tarjeta_lectura", "saldo_detalle"}

# Grupos de hallazgos de la tarjeta de lecturas (campos de la entidad).
GRUPOS_TARJETA = (
    "errorConsumo",
    "errorLecturas",
    "errorReinstalacion",
    "errorServicio",
)

# Grupos de hallazgos del saldo-detalle (campos de la entidad).
GRUPOS_SALDO = (
    "cobroIndebido",
    "mora",
    "mesesNoPagados",
)


def problemas_de_targeta(targeta: TargetaLecturas) -> list[ProblemaNormado]:
    """Cada string de cada grupo de error se vuelve un ProblemaNormado.

    El `tipo` es el nombre del grupo (para elegir la query canónica) y el
    `detalle` es el texto concreto con cifras (para dárselo al LLM)."""
    problemas: list[ProblemaNormado] = []
    for grupo in GRUPOS_TARJETA:
        for detalle in getattr(targeta, grupo, []) or []:
            problemas.append(ProblemaNormado(tipo=grupo, detalle=detalle))
    return problemas


def problemas_de_saldo(saldo: SaldoDetalle) -> list[ProblemaNormado]:
    """Cada string de cada grupo de problema se vuelve un ProblemaNormado.

    El `tipo` es el nombre del grupo (para elegir la query canónica) y el
    `detalle` es el texto concreto con fechas (para dárselo al LLM)."""
    problemas: list[ProblemaNormado] = []
    for grupo in GRUPOS_SALDO:
        for detalle in getattr(saldo, grupo, []) or []:
            problemas.append(ProblemaNormado(tipo=grupo, detalle=detalle))
    return problemas


def extraer_problemas(medio_id: str, entidad) -> list[ProblemaNormado]:
    """Dispatcher por medio probatorio. Devuelve [] para medios aún no
    soportados (inspección interna/externa, corte/reapertura)."""
    if medio_id == "tarjeta_lectura":
        return problemas_de_targeta(entidad)
    if medio_id == "saldo_detalle":
        return problemas_de_saldo(entidad)
    # TODO: inspeccion_interna, inspeccion_externa, corte_reapertura
    logger.debug("Normalizador de problemas no implementado para: %s", medio_id)
    return []
