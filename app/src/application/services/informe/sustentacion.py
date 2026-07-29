"""Ensambla el Informe de Sustentación del Régimen de Facturación a partir de
los datos ya analizados en memoria (tarjeta de lecturas + record de facturación
+ datos del reclamo). Función pura, sin efectos secundarios ni llamadas a EMAPA
— el gemelo estructurado de `construir_texto_informe` del informe de atención.
"""

import re
import logging

from app.src.core.model.informe_atencion import InformeAtencion
from app.src.core.model.sustentacion import (
    SustentacionData, ClientePredio, FacturacionEvaluada, ValoresCalculados,
    FichaMedidor, Conexion, LecturaHito, FilaHistorico, CategoriaUso,
)

logger = logging.getLogger("services.sustentacion")

# --- Placeholders fijos: campos del PDF que EMAPA no expone en tarjeta/record.
# Se imprimen igual que en el documento oficial para conservar la estructura.
PLACEHOLDER = "[Ninguno]"
NO_HOMOLOGADO = "NO HOMOLOGADO"
SOLICITANTE = "EPS EMAPA SAN MARTIN S.A."
METODOLOGIA_PROMEDIO = "LAS 6 ULTIMAS LECTURAS VALIDAS DEL MES"

# tipopromedio (código EMAPA) -> texto de MODALIDAD DE FACTURACIÓN del informe.
MODALIDAD = {"0": "DIF. LECTURAS", "1": "ASIGNADO", "2": "PROMEDIO"}
TIPO_ASIGNADO = "1"

# Matriz CATEGORÍA / UNIDADES DE USO: las 6 columnas fijas del encabezado del
# PDF y los códigos catetar de EMAPA que caen en cada una.
CATEGORIAS_MATRIZ = [
    ("DOM", "DOMÉSTICO", {"001", "101"}),
    ("DOM 2", "DOMÉSTICO 2", {"002"}),
    ("COM", "COMERCIAL", {"015"}),
    ("IND", "INDUSTRIAL", {"022"}),
    ("EST", "ESTATAL", {"024"}),
    ("SOC", "SOCIAL", {"026", "027"}),
]

MESES_NUM = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MES_ABREV = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set",
             "Oct", "Nov", "Dic"]


def _parse_mesanio(texto: str | None) -> tuple[int, int] | None:
    """'SETIEMBRE-2022' -> (2022, 9). None si no se puede interpretar."""
    if not texto:
        return None
    m = re.match(r"\s*([A-Za-zÁÉÍÓÚñÑ]+)[\s\-/]+(\d{4})", str(texto).strip())
    if not m:
        return None
    mes = MESES_NUM.get(m.group(1).lower())
    return (int(m.group(2)), mes) if mes else None


def _entidad(informe: InformeAtencion, medio_id: str) -> dict:
    """Devuelve el `entidad` (asdict) del bloque del medio, o {} si no se analizó."""
    bloque = next((b for b in informe.bloques if b.medio_id == medio_id), None)
    return (bloque.entidad or {}) if bloque else {}


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mes_abrev(anio: int | None, mes: int | None) -> str | None:
    if not anio or not mes or not (1 <= mes <= 12):
        return None
    return f"{MES_ABREV[mes - 1]}-{str(anio)[-2:]}"


def _volumen(fila: dict) -> float | None:
    """Volumen facturado del mes: consumofac si es >0, si no el consumo real."""
    fac = _num(fila.get("consumofac"))
    return fac if fac else _num(fila.get("consumo"))


def _marca_reclamo(fila: dict) -> str:
    """Marca RECLAMADO/REFACTURADO de una fila del record (o '' si ninguna)."""
    if (_num(fila.get("impdeudareclamo")) or 0) > 0:
        return "RECLAMADO"
    if (_num(fila.get("c_impmesrebaja")) or 0) > 0:
        return "REFACTURADO"
    return ""


def _fila_mes(registros: list[dict], ref: tuple[int, int] | None) -> dict | None:
    """Fila del mes reclamado (o la última disponible si no hay match)."""
    if ref:
        ra, rm = ref
        fila = next(
            (r for r in registros if _int(r.get("anio")) == ra and _int(r.get("mes")) == rm),
            None,
        )
        if fila is not None:
            return fila
    return registros[-1] if registros else None


def _matriz_categorias(codigo_catetar: str | None) -> list[CategoriaUso]:
    """Construye las 6 columnas de la matriz, marcando la del suministro."""
    cod = str(codigo_catetar).strip() if codigo_catetar is not None else None
    return [
        CategoriaUso(codigo=col, nombre=nombre, es_cliente=(cod in codigos))
        for col, nombre, codigos in CATEGORIAS_MATRIZ
    ]


def construir_sustentacion(informe: InformeAtencion) -> SustentacionData:
    tarjeta = _entidad(informe, "tarjeta_lectura")
    record = _entidad(informe, "record_facturacion")
    reclamo = informe.datos_reclamo

    lecturas: list[dict] = tarjeta.get("registros") or []   # orden cronológico ascendente
    facturas: list[dict] = record.get("registros") or []    # orden cronológico ascendente

    ref = _parse_mesanio(reclamo.meses_reclamados if reclamo else None)

    # --- Lecturas: fila del mes reclamado (+ la previa, para "lectura anterior") ---
    fila_lect = _fila_mes(lecturas, ref)
    fila_prev = None
    if fila_lect is not None and fila_lect in lecturas:
        idx = lecturas.index(fila_lect)
        fila_prev = lecturas[idx - 1] if idx > 0 else None

    lect = fila_lect or {}
    prev = fila_prev or {}
    lectura_actual = LecturaHito(
        fecha=lect.get("fechalecturault"),
        lectura=_num(lect.get("lecturaultima")),
        observacion=lect.get("desestadolectura"),
    )
    lectura_anterior = LecturaHito(
        fecha=prev.get("fechalecturault"),
        lectura=_num(prev.get("lecturaultima")),
        observacion=prev.get("desestadolectura"),
    )

    dif_lecturas = None
    if lectura_actual.lectura is not None and lectura_anterior.lectura is not None:
        dif_lecturas = lectura_actual.lectura - lectura_anterior.lectura
    elif lect:
        la, lu = _num(lect.get("lecturaanterior")), _num(lect.get("lecturaultima"))
        dif_lecturas = (lu - la) if (la is not None and lu is not None) else None

    # --- Record: fila del mes reclamado (modalidad, volumen, consumo asignado) ---
    fac = _fila_mes(facturas, ref) or {}
    tipoprom = str(fac.get("tipopromedio")).strip() if fac.get("tipopromedio") is not None else None
    modalidad = MODALIDAD.get(tipoprom)
    consumo_asignado = _num(fac.get("consumo")) if tipoprom == TIPO_ASIGNADO else 0.0

    # --- Histórico de consumos (más reciente primero, como el PDF) ---
    historico = [
        FilaHistorico(
            mes_anio=_mes_abrev(_int(f.get("anio")), _int(f.get("mes"))),
            modalidad=MODALIDAD.get(str(f.get("tipopromedio")).strip()) if f.get("tipopromedio") is not None else None,
            volumen=_volumen(f),
            marca=_marca_reclamo(f),
        )
        for f in reversed(facturas)
    ]

    data = SustentacionData(
        cliente=ClientePredio(
            suministro=reclamo.codcliente if reclamo else None,
            nombre_usuario=tarjeta.get("propietario") or (reclamo.propietario if reclamo else None),
            dni=reclamo.dni if reclamo else None,
            direccion=tarjeta.get("direccion"),
            mes_facturacion=reclamo.meses_reclamados if reclamo else None,
            categorias=_matriz_categorias(tarjeta.get("categoria")),
        ),
        facturacion=FacturacionEvaluada(
            modalidad=modalidad,
            volumen_facturado=_volumen(fac),
            lectura_anterior=lectura_anterior,
            lectura_actual=lectura_actual,
        ),
        valores=ValoresCalculados(
            dif_lecturas=dif_lecturas,
            promedio_historico=_num(lect.get("lecturapromedio")),
            consumo_asignado=consumo_asignado,
            meses_promedio=METODOLOGIA_PROMEDIO,
            observacion_consumo=lect.get("desestadolectura"),
        ),
        historico=historico,
        medidor=FichaMedidor(
            nro_serie=tarjeta.get("nro_medidor"),
            estado=lect.get("desestadomed"),
            marca=tarjeta.get("marca_medidor"),
            modelo=PLACEHOLDER,                 # EMAPA no expone el modelo real
            diametro=tarjeta.get("diametro"),
            modelo_homologacion=NO_HOMOLOGADO,
            nro_certificado=PLACEHOLDER,
            fecha_instalacion=tarjeta.get("fecha_instalacion_medidor"),
            fecha_verificacion=tarjeta.get("fecha_verificacion") or PLACEHOLDER,
            tipo_verificacion=tarjeta.get("tipo_verificacion") or PLACEHOLDER,
            solicitante=SOLICITANTE,
            uvm=PLACEHOLDER,
        ),
        conexion=Conexion(
            fecha_nacimiento=tarjeta.get("fecha_instalacion_conexion"),
            fecha_instalacion_medidor=tarjeta.get("fecha_instalacion_medidor"),
            nro_acta=PLACEHOLDER,
        ),
    )
    logger.info(
        "[SUSTENTACION] Ensamblada | reclamo=%s | meses_historico=%d | mes_ref=%s",
        informe.reclamo, len(historico), ref,
    )
    return data
