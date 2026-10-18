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
    "descensoConsumo",
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


# Las observaciones libres pueden registrar hallazgos, negaciones, sospechas o
# declaraciones de terceros. Se preserva esa modalidad en cada mención.
_NEGACION_FUGA = re.compile(
    r"\b(?:no\s+(?:se\s+)?(?:detect\w*|encontr\w*|observ\w*|hay|existe\w*|present\w*)|"
    r"se\s+descart\w*|sin\s+(?:evidencia\s+de\s+)?fugas?)\b", re.IGNORECASE,
)
_SOSPECHA_FUGA = re.compile(
    r"\b(?:(?:se\s+)?(?:sospech\w*|posible|probable|podr[ií]a|aparente|presunta|hipot[eé]tica)|"
    r"si\s+(?:se\s+)?(?:detect\w*|hubier\w*|exist\w*))\b",
    re.IGNORECASE,
)
_ATRIBUCION_TERCERO = re.compile(
    r"\b(?:(?:usuario|cliente|titular|responsable|vecino|tercero)\s+"
    r"(?:refier\w*|indic\w*|manifest\w*|señal\w*|report\w*|afirm\w*)|"
    r"(?:seg[uú]n|de\s+acuerdo\s+con)\s+(?:el\s+|la\s+)?"
    r"(?:usuario|cliente|titular|responsable|vecino|tercero))\b",
    re.IGNORECASE,
)


def _fugas_desde_observaciones(
    textos: list[str | None] | list[tuple[str, str | None]],
) -> list[ProblemaNormado]:
    """Conserva y clasifica cada cláusula que menciona una fuga.

    Las negaciones verbales no incluyen ``no visible``. Una mención incierta o
    atribuida a un tercero nunca se convierte en fuga confirmada.
    """
    problemas: list[ProblemaNormado] = []
    vistos: set[tuple[str, str, str]] = set()
    for entrada in textos:
        fuente, texto = entrada if isinstance(entrada, tuple) else ("observacion", entrada)
        if not texto or "FUGA" not in texto.upper():
            continue
        original = str(texto).strip()
        clausulas = re.split(
            r"(?<=[.!?;])\s+|\s+(?=(?:pero|sin embargo|aunque|y)\b[^.!?;]*\bfugas?\b)",
            original,
            flags=re.IGNORECASE,
        )
        for clausula in clausulas:
            if "FUGA" not in clausula.upper():
                continue
            detalle = re.sub(r"\s+", " ", clausula).strip(" ;")
            if _NEGACION_FUGA.search(detalle):
                tipo = "fugaNoDetectada"
            elif _SOSPECHA_FUGA.search(detalle) or "?" in detalle:
                tipo = "fugaSospechada"
            elif _ATRIBUCION_TERCERO.search(detalle):
                tipo = "fugaReferida"
            elif re.search(r"\bNO\s+VISIBLE\b", detalle, re.IGNORECASE):
                tipo = "fugaNoVisible"
            elif re.search(r"\bVISIBLE\b", detalle, re.IGNORECASE):
                tipo = "fugaVisible"
            else:
                tipo = "fugas"
            clave = (tipo, detalle.casefold(), fuente)
            if clave in vistos:
                continue
            vistos.add(clave)
            problemas.append(ProblemaNormado(
                tipo=tipo,
                detalle=detalle,
                fuente=fuente,
                texto_original=original,
            ))
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
        problemas.append(ProblemaNormado(tipo="fugas", detalle=detalle, fuente="fugas"))
        fuga_estructurada = True

    # Las observaciones siempre se conservan. Un campo estructurado no las
    # reemplaza: si difieren, el conflicto queda visible para el análisis.
    problemas_obs = _fugas_desde_observaciones([
        ("observacionmed", inspeccion.observacionmed),
        ("observacionsum", inspeccion.observacionsum),
    ])
    problemas.extend(problemas_obs)
    tipos_obs = {p.tipo for p in problemas_obs}
    estructurado_sin_fuga = inspeccion.fugas == ind["fugas"]["0"]
    obs_afirma = bool(tipos_obs & {"fugas", "fugaVisible", "fugaNoVisible"})
    obs_niega = "fugaNoDetectada" in tipos_obs
    if (fuga_estructurada and obs_niega) or (estructurado_sin_fuga and obs_afirma):
        problemas.append(ProblemaNormado(
            tipo="contradiccionFuga",
            detalle=(
                "Existe contradicción entre el campo estructurado de fugas y "
                "las observaciones; requiere revisión conjunta de ambas fuentes."
            ),
            fuente="fugas/observaciones",
        ))

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
        ("obsinsinteriores", inspeccion.obsinsinteriores),
        ("observaciones", inspeccion.observaciones),
        ("obsperrepins", inspeccion.obsperrepins),
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
