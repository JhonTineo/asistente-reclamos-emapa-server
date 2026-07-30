"""Normaliza los problemas detectados en el preprocesamiento a una lista
uniforme de ProblemaNormado, independiente del medio probatorio.
"""

import re
import logging

from app.src.core.model.targeta_lecturas import TargetaLecturas
from app.src.core.model.saldo_detalle import SaldoDetalle
from app.src.core.model.record_facturacion import RecordFacturacion
from app.src.core.model.corte_reapertura import CorteReapertura
from app.src.core.model.inspeccion_externa import InspeccionExterna
from app.src.core.model.inspeccion_interna import InspeccionInterna
from app.src.core.model.indicadores.inspeccion_externa_indicadores import INDICADORES_INSPECCION_EXTERNA
from app.src.core.model.indicadores.inspeccion_interna_indicadores import INDICADORES_INSPECCION_INTERNA
from app.src.core.model.informe_atencion import ProblemaNormado

logger = logging.getLogger("services.problemas_normalizer")

# Medios que ya tienen detección de problemas implementada.
MEDIOS_SOPORTADOS = {
    "tarjeta_lectura",
    "saldo_detalle",
    "record_facturacion",
    "corte_reapertura",
    "inspeccion_externa",
    "inspeccion_interna",
}

# Grupos de hallazgos de la tarjeta de lecturas (campos de la entidad).
GRUPOS_TARJETA = (
    "errorConsumo",
    "errorLecturas",
    "errorReinstalacion",
    "errorServicio",
    "fugaReparada",
)

# Grupos de hallazgos del saldo-detalle (campos de la entidad).
GRUPOS_SALDO = (
    "cobroIndebido",
    "mora",
    "mesesNoPagados",
)

# Grupos de hallazgos del record de facturación (campos de la entidad).
GRUPOS_RECORD = (
    "mesesPromediados",
    "rachaPromediados",
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


def problemas_de_record(record: RecordFacturacion) -> list[ProblemaNormado]:
    """mesesPromediados / rachaPromediados ya son oraciones completas: se usan
    tal cual como detalle."""
    problemas: list[ProblemaNormado] = []
    for grupo in GRUPOS_RECORD:
        for detalle in getattr(record, grupo, []) or []:
            problemas.append(ProblemaNormado(tipo=grupo, detalle=detalle))
    return problemas


def problemas_de_corte(corte: CorteReapertura) -> list[ProblemaNormado]:
    """mesesCortados son solo etiquetas 'AAAA-MM': se envuelven en una oración
    legible. reclamosPrevios ya viene formateado ('AAAA-MM: reclamo N° …')."""
    problemas: list[ProblemaNormado] = []
    for mes in corte.mesesCortados or []:
        problemas.append(ProblemaNormado(tipo="mesesCortados", detalle=f"Servicio cortado en {mes}."))
    for detalle in corte.reclamosPrevios or []:
        problemas.append(ProblemaNormado(tipo="reclamosPrevios", detalle=detalle))
    return problemas


# Las inspecciones registran la fuga hallada dentro del predio en un campo de
# OBSERVACIÓN de texto libre (p.ej. obsinsinteriores), no en un campo estructurado.
# Como la fuga es el hallazgo que decide muchos reclamos de consumo (Art. 88.3:
# visible → diferencia de lecturas; no visible reparada → promedio), se extrae de
# ahí a un ProblemaNormado con regla, clasificándola en visible / no visible.
def _fugas_desde_observaciones(textos: list[str | None]) -> list[ProblemaNormado]:
    """Busca menciones de 'FUGA' en campos de observación libre y arma un
    ProblemaNormado por cada mención (dedup por detalle). El `tipo` distingue
    fugaNoVisible / fugaVisible / fugas (genérica) para dirigir el RAG; el
    `detalle` es la oración que contiene la fuga (desde 'FUGA' hasta el punto)."""
    problemas: list[ProblemaNormado] = []
    vistos: set[str] = set()
    for texto in textos:
        if not texto or "FUGA" not in texto.upper():
            continue
        # Cláusula: desde la primera aparición de FUGA hasta el siguiente punto.
        idx = texto.upper().find("FUGA")
        fin = texto.find(".", idx)
        fragmento = (texto[idx:] if fin == -1 else texto[idx:fin]).strip()
        fragmento = re.sub(r"\s+", " ", fragmento)
        detalle = fragmento.capitalize()
        if not detalle or detalle in vistos:
            continue
        vistos.add(detalle)
        frag_upper = fragmento.upper()
        if "NO VISIBLE" in frag_upper:
            tipo = "fugaNoVisible"
        elif "VISIBLE" in frag_upper:
            tipo = "fugaVisible"
        else:
            tipo = "fugas"
        problemas.append(ProblemaNormado(tipo=tipo, detalle=detalle))
    return problemas


def problemas_de_inspeccion_externa(inspeccion: InspeccionExterna) -> list[ProblemaNormado]:
    """Hallazgos: condición atípica, fugas, equipo en mal estado (medidor,
    caja, conexión). Las observaciones NO se consideran problema (son texto
    libre y no siempre indican una anomalía).

    IMPORTANTE: `_construir_inspeccion` (pre_inspeccion_externa_service) ya
    traduce los códigos crudos de EMAPA a texto legible antes de armar la
    entidad, así que aquí se compara contra el texto "normal" (no contra el
    código "001"/"0"/etc., que ya no está presente en el campo)."""
    ind = INDICADORES_INSPECCION_EXTERNA
    problemas: list[ProblemaNormado] = []

    if inspeccion.atipico and inspeccion.atipico != ind["atipico"]["0"]:
        problemas.append(ProblemaNormado(tipo="atipico", detalle=inspeccion.atipico))

    fuga_estructurada = False
    if inspeccion.fugas and inspeccion.fugas != ind["fugas"]["0"]:
        detalle = inspeccion.fugas
        tipofugas_normal = {ind["tipofugas"]["000"], ind["tipofugas"]["001"]}
        if inspeccion.tipofugas and inspeccion.tipofugas not in tipofugas_normal:
            detalle = f"{detalle} {inspeccion.tipofugas}"
        problemas.append(ProblemaNormado(tipo="fugas", detalle=detalle))
        fuga_estructurada = True

    # Fuga mencionada en las observaciones (solo si no vino ya por el campo
    # estructurado, para no duplicar el mismo hallazgo).
    if not fuga_estructurada:
        problemas.extend(_fugas_desde_observaciones([inspeccion.observacionmed, inspeccion.observacionsum]))

    if inspeccion.funcionamed and inspeccion.funcionamed != ind["funcionamed"]["1"]:
        problemas.append(ProblemaNormado(tipo="equipo", detalle=inspeccion.funcionamed))

    if inspeccion.estadocaja and inspeccion.estadocaja != ind["estadocaja"]["001"]:
        problemas.append(ProblemaNormado(tipo="equipo", detalle=inspeccion.estadocaja))

    if inspeccion.estconexion and inspeccion.estconexion != ind["estconexion"]["001"]:
        problemas.append(ProblemaNormado(tipo="equipo", detalle=inspeccion.estconexion))

    return problemas


def problemas_de_inspeccion_interna(inspeccion: InspeccionInterna) -> list[ProblemaNormado]:
    """Hallazgos: condición atípica y abastecimiento anormal. Las
    observaciones NO se consideran problema.

    Mismo cuidado que en la inspección externa: se compara contra el texto ya
    traducido, no contra el código crudo."""
    ind = INDICADORES_INSPECCION_INTERNA
    problemas: list[ProblemaNormado] = []

    if inspeccion.atipico and inspeccion.atipico != ind["atipico"]["0"]:
        problemas.append(ProblemaNormado(tipo="atipico", detalle=inspeccion.atipico))

    if inspeccion.estadoabas and inspeccion.estadoabas != ind["estadoabas"]["1"]:
        problemas.append(ProblemaNormado(tipo="equipo", detalle=inspeccion.estadoabas))

    # Fuga hallada dentro del predio: vive en las observaciones libres.
    problemas.extend(_fugas_desde_observaciones([
        inspeccion.obsinsinteriores, inspeccion.observaciones, inspeccion.obsperrepins,
    ]))

    return problemas


def extraer_problemas(medio_id: str, entidad) -> list[ProblemaNormado]:
    """Dispatcher por medio probatorio."""
    if medio_id == "tarjeta_lectura":
        return problemas_de_targeta(entidad)
    if medio_id == "saldo_detalle":
        return problemas_de_saldo(entidad)
    if medio_id == "record_facturacion":
        return problemas_de_record(entidad)
    if medio_id == "corte_reapertura":
        return problemas_de_corte(entidad)
    if medio_id == "inspeccion_externa":
        return problemas_de_inspeccion_externa(entidad)
    if medio_id == "inspeccion_interna":
        return problemas_de_inspeccion_interna(entidad)
    logger.debug("Normalizador de problemas no implementado para: %s", medio_id)
    return []
