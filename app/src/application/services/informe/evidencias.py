"""Expediente de evidencias del reclamo: los DATOS que respaldan el veredicto,
listos para graficar (consumo mensual, indicadores, lecturas, inspecciones,
línea de tiempo y verificaciones determinantes).

Función pura, igual que `construir_sustentacion`: lee lo que ya está analizado
en memoria (bloques de los medios + datos del reclamo + objetivos). No llama a
EMAPA ni al LLM, no altera el informe y no decide nada: el veredicto lo sigue
fijando la puerta lógica de la conclusión. Si un medio aún no se analizó, su
parte sale vacía y `disponible` lo indica.
"""

import re
from datetime import date

from app.src.core.model.informe_atencion import InformeAtencion
from app.src.core.model.indicadores.inspeccion_externa_indicadores import INDICADORES_INSPECCION_EXTERNA
from app.src.core.model.indicadores.inspeccion_interna_indicadores import INDICADORES_INSPECCION_INTERNA
from app.src.application.services.pre_proces.pre_targeta_lecturas_service import FACTOR_ELEVADO, FACTOR_NORMAL

MESES_NUM = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MES_ABREV = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Set", "Oct", "Nov", "Dic"]
MES_NOMBRE = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
              "setiembre", "octubre", "noviembre", "diciembre"]
FORMA_FACTURACION = {"0": "Lectura", "1": "Asignado", "2": "Promedio"}
MESES_BASE = 6   # meses previos al reclamado que forman el promedio de comparación

# Textos (ya traducidos por el preprocesamiento) que significan un hallazgo
# desfavorable en la inspección externa. El resto se considera conforme.
_EXT = INDICADORES_INSPECCION_EXTERNA
ALERTAS_EXTERNA = {
    _EXT["fugas"]["1"], _EXT["funcionamed"]["0"], _EXT["estadocaja"]["002"],
    _EXT["estconexion"]["002"], _EXT["atipico"]["1"],
    _EXT["tipofugas"]["002"], _EXT["tipofugas"]["003"], _EXT["tipofugas"]["004"],
}
ALERTAS_INTERNA = {INDICADORES_INSPECCION_INTERNA["atipico"]["1"],
                   INDICADORES_INSPECCION_INTERNA["estadoabas"]["2"]}

PUNTOS_AGUA = [("inodoro", "Inodoros"), ("lavado", "Lavatorios"), ("ducha", "Duchas"),
               ("urinario", "Urinarios"), ("bidet", "Bidés"), ("grifo", "Grifos"),
               ("cisterna", "Cisternas"), ("tanque", "Tanques elevados"), ("piscina", "Piscinas")]

# Medio -> sección del panel que muestra su prueba.
SECCION_DE_MEDIO = {
    "tarjeta_lectura": "consumo", "record_facturacion": "consumo",
    "inspeccion_externa": "inspeccion", "inspeccion_interna": "inspeccion",
    "corte_reapertura": "linea_tiempo", "saldo_detalle": "linea_tiempo",
}


def periodos_reclamados(texto: str | None) -> list[tuple[int, int]]:
    """'SETIEMBRE-2026' o 'JULIO-2026, AGOSTO-2026' -> [(2026, 7), (2026, 8)]."""
    if not texto:
        return []
    res = []
    for nombre, anio in re.findall(r"([A-Za-zÁÉÍÓÚñÑ]+)[\s\-/]+(\d{4})", str(texto)):
        mes = MESES_NUM.get(nombre.lower())
        if mes and (int(anio), mes) not in res:
            res.append((int(anio), mes))
    return sorted(res)


def _entidad(informe: InformeAtencion, medio_id: str) -> dict:
    bloque = next((b for b in informe.bloques if b.medio_id == medio_id), None)
    return (bloque.entidad or {}) if bloque else {}


def _num(v) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _int(v) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None


def _fecha_corta(texto) -> str | None:
    """'2026-09-19 08:18:21.0' -> '2026-09-19'. Acepta también dd/mm/aaaa."""
    if not texto:
        return None
    t = str(texto).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def _redondear(v: float | None, dec: int = 1) -> float | None:
    return None if v is None else round(v, dec)


def construir_serie(informe: InformeAtencion) -> list[dict]:
    """Une tarjeta de lecturas y record de facturación por (año, mes)."""
    reclamados = set(periodos_reclamados(informe.datos_reclamo.meses_reclamados if informe.datos_reclamo else None))
    filas: dict[tuple[int, int], dict] = {}

    for r in _entidad(informe, "tarjeta_lectura").get("registros") or []:
        anio, mes = _int(r.get("anio")), _int(r.get("mes"))
        if not anio or not mes:
            continue
        ant, act = _num(r.get("lecturaanterior")), _num(r.get("lecturaultima"))
        consumo = _num(r.get("consumo"))
        if consumo is None and ant is not None and act is not None:
            consumo = act - ant
        filas.setdefault((anio, mes), {}).update({
            "lectura_anterior": ant, "lectura_actual": act, "consumo_medido": consumo,
            "fecha_lectura": _fecha_corta(r.get("fechalecturault")),
            "estado_lectura": r.get("estadolectura_texto") or r.get("desestadolectura"),
            "nromed": r.get("nromed"),
        })

    for r in _entidad(informe, "record_facturacion").get("registros") or []:
        anio, mes = _int(r.get("anio")), _int(r.get("mes"))
        if not anio or not mes:
            continue
        f = filas.setdefault((anio, mes), {})
        f["consumo_facturado"] = _num(r.get("consumofac"))
        f["importe"] = _num(r.get("impmestotal"))
        f["forma_facturacion"] = FORMA_FACTURACION.get(str(r.get("tipopromedio")), r.get("tipopromedio_texto"))
        if f.get("consumo_medido") is None:
            f["consumo_medido"] = _num(r.get("consumo"))
        rebaja = _num(r.get("c_impmesrebaja"))
        f["refacturado"] = bool(rebaja and rebaja > 0)

    serie = []
    for (anio, mes) in sorted(filas):
        f = filas[(anio, mes)]
        valor = f.get("consumo_facturado")
        if valor is None:
            valor = f.get("consumo_medido")
        serie.append({
            "anio": anio, "mes": mes,
            "etiqueta": f"{MES_ABREV[mes - 1]} {anio}",
            "etiqueta_corta": MES_ABREV[mes - 1],
            "consumo": valor,
            "consumo_medido": f.get("consumo_medido"),
            "consumo_facturado": f.get("consumo_facturado"),
            "importe": f.get("importe"),
            "forma_facturacion": f.get("forma_facturacion"),
            "lectura_anterior": f.get("lectura_anterior"),
            "lectura_actual": f.get("lectura_actual"),
            "fecha_lectura": f.get("fecha_lectura"),
            "estado_lectura": f.get("estado_lectura"),
            "refacturado": f.get("refacturado", False),
            "reclamado": (anio, mes) in reclamados,
        })
    return serie


def calcular_indicadores(serie: list[dict]) -> dict | None:
    """Compara el mes reclamado (el último con datos) contra los meses previos."""
    reclamados = [s for s in serie if s["reclamado"] and s["consumo"] is not None]
    if not reclamados:
        return None
    objetivo = reclamados[-1]
    primero = min((s["anio"], s["mes"]) for s in reclamados)
    base = [s for s in serie if (s["anio"], s["mes"]) < primero and not s["reclamado"] and s["consumo"] is not None]
    base = base[-MESES_BASE:]
    valores = [s["consumo"] for s in base]
    promedio = sum(valores) / len(valores) if valores else None
    veces = objetivo["consumo"] / promedio if promedio else None

    if veces is None:
        nivel, texto = "sin_base", "No hay meses previos suficientes para comparar el consumo."
    elif veces >= FACTOR_ELEVADO:
        nivel = "elevado"
        texto = (f"El consumo de {MES_NOMBRE[objetivo['mes'] - 1]} ({objetivo['consumo']:g} m³) es "
                 f"{veces:.2f} veces el promedio de los {len(valores)} meses previos ({promedio:.1f} m³): "
                 "un incremento marcado.")
    elif veces >= FACTOR_NORMAL:
        nivel = "superior"
        texto = (f"El consumo de {MES_NOMBRE[objetivo['mes'] - 1]} ({objetivo['consumo']:g} m³) es "
                 f"{veces:.2f} veces el promedio de los {len(valores)} meses previos ({promedio:.1f} m³): "
                 "superior a lo habitual, sin llegar a duplicarlo.")
    else:
        nivel = "habitual"
        texto = (f"El consumo de {MES_NOMBRE[objetivo['mes'] - 1]} ({objetivo['consumo']:g} m³) es "
                 f"{veces:.2f} veces el promedio de los {len(valores)} meses previos ({promedio:.1f} m³): "
                 "dentro de lo habitual para este suministro.")
    if valores and min(valores) <= objetivo["consumo"] <= max(valores):
        texto += f" Está dentro del rango que el usuario registró en esos meses ({min(valores):g}–{max(valores):g} m³)."

    return {
        "periodo": objetivo["etiqueta"],
        "anio": objetivo["anio"], "mes": objetivo["mes"],
        "consumo_reclamado": objetivo["consumo"],
        "consumo_medido": objetivo["consumo_medido"],
        "importe_reclamado": objetivo["importe"],
        "lectura_anterior": objetivo["lectura_anterior"],
        "lectura_actual": objetivo["lectura_actual"],
        "fecha_lectura": objetivo["fecha_lectura"],
        "forma_facturacion": objetivo["forma_facturacion"],
        "promedio_previo": _redondear(promedio),
        "meses_base": len(valores),
        "periodo_base": f"{base[0]['etiqueta']} – {base[-1]['etiqueta']}" if base else None,
        "minimo_previo": min(valores) if valores else None,
        "maximo_previo": max(valores) if valores else None,
        "veces_promedio": _redondear(veces, 2),
        "variacion_pct": _redondear((veces - 1) * 100, 0) if veces is not None else None,
        "nivel": nivel,
        "interpretacion": texto,
    }


def _punto(punto: str, valor, alertas: set[str]) -> dict | None:
    if valor in (None, ""):
        return None
    texto = str(valor)
    return {"punto": punto, "resultado": texto, "estado": "alerta" if texto in alertas else "conforme"}


def construir_inspeccion_externa(informe: InformeAtencion) -> dict | None:
    e = _entidad(informe, "inspeccion_externa")
    if not e or not any(e.get(k) for k in ("nroinspeccion", "funcionamed", "fugas", "estadocaja")):
        return None
    puntos = [p for p in (
        _punto("Funcionamiento del medidor", e.get("funcionamed"), ALERTAS_EXTERNA),
        _punto("Fugas de agua", e.get("fugas"), ALERTAS_EXTERNA),
        _punto("Tipo de fuga", e.get("tipofugas") if e.get("tipofugas") not in ("[No especificado]",) else None, ALERTAS_EXTERNA),
        _punto("Caja del medidor", e.get("estadocaja"), ALERTAS_EXTERNA),
        _punto("Conexión", e.get("estconexion"), ALERTAS_EXTERNA),
        _punto("Condiciones atípicas", e.get("atipico"), ALERTAS_EXTERNA),
    ) if p]
    obs = [str(e[k]).strip() for k in ("observacionmed", "observacionsum") if e.get(k) and str(e[k]).strip()]
    return {
        "nroinspeccion": str(e.get("nroinspeccion")) if e.get("nroinspeccion") is not None else None,
        "fecha": _fecha_corta(e.get("fechainspeccion")),
        "puntos": puntos,
        "observaciones": obs,
        "alertas": sum(1 for p in puntos if p["estado"] == "alerta"),
    }


def construir_inspeccion_interna(informe: InformeAtencion) -> dict | None:
    e = _entidad(informe, "inspeccion_interna")
    if not e or not any(e.get(k) for k in ("nroinspeccion", "estadoabas", "atipico", "puntos_agua")):
        return None
    totales = {}
    for unidad in e.get("puntos_agua") or []:
        for clave, _ in PUNTOS_AGUA:
            totales[clave] = totales.get(clave, 0) + (_num(unidad.get(clave)) or 0)
    puntos_agua = [{"tipo": nombre, "cantidad": int(totales[clave])}
                   for clave, nombre in PUNTOS_AGUA if totales.get(clave)]
    puntos = [p for p in (
        _punto("Abastecimiento", e.get("estadoabas"), ALERTAS_INTERNA),
        _punto("Consumo atípico en la inspección", e.get("atipico"), ALERTAS_INTERNA),
    ) if p]
    obs = [str(e[k]).strip() for k in ("obsinsinteriores", "observaciones", "obsperrepins") if e.get(k) and str(e[k]).strip()]
    return {
        "nroinspeccion": str(e.get("nroinspeccion")) if e.get("nroinspeccion") is not None else None,
        "fecha": _fecha_corta(e.get("fechainspeccion")),
        "puntos": puntos,
        "puntos_agua": puntos_agua,
        "total_puntos_agua": int(sum(totales.values())),
        "unidades_uso": len(e.get("puntos_agua") or []),
        "observaciones": obs,
        "alertas": sum(1 for p in puntos if p["estado"] == "alerta"),
    }


def construir_linea_tiempo(informe: InformeAtencion, indicadores: dict | None,
                           externa: dict | None, interna: dict | None) -> list[dict]:
    r = informe.datos_reclamo
    hitos = []

    def add(fecha, texto, tipo):
        f = _fecha_corta(fecha)
        if f:
            hitos.append({"fecha": f, "texto": texto, "tipo": tipo})

    if indicadores and indicadores.get("fecha_lectura"):
        lect = indicadores.get("lectura_actual")
        add(indicadores["fecha_lectura"],
            f"Lectura del mes reclamado ({lect:g} m³)" if lect is not None else "Lectura del mes reclamado", "lectura")
    if r:
        add(r.fecha_recepcion, "El usuario presenta el reclamo", "reclamo")
        add(r.fecha_notificacion_inspeccion, "Se notifica la inspección", "tramite")
    if externa:
        add(externa.get("fecha"), "Inspección externa", "inspeccion")
    if interna:
        add(interna.get("fecha"), "Inspección interna", "inspeccion")
    if r:
        add(r.fecha_reunion, "Reunión de conciliación", "tramite")
        add(r.fecha_max_resolucion, "Plazo máximo de resolución", "plazo")
    # Mismo día y texto: una sola vez (externa e interna suelen coincidir).
    vistos, unicos = set(), []
    for h in sorted(hitos, key=lambda h: h["fecha"]):
        if (h["fecha"], h["texto"]) not in vistos:
            vistos.add((h["fecha"], h["texto"]))
            unicos.append(h)
    return unicos


def construir_verificaciones(informe: InformeAtencion) -> list[dict]:
    """Objetivos determinantes con su resultado, para el resumen del veredicto."""
    return [{
        "id": o.id,
        "descripcion": o.descripcion,
        "medio": o.medio,
        "seccion": SECCION_DE_MEDIO.get(o.medio or "", "consumo"),
        "resultado": o.resultado,
        "evidencia": o.evidencia,
    } for o in informe.objetivos if o.determinante]


def construir_evidencias(informe: InformeAtencion) -> dict:
    serie = construir_serie(informe)
    indicadores = calcular_indicadores(serie)
    externa = construir_inspeccion_externa(informe)
    interna = construir_inspeccion_interna(informe)
    r = informe.datos_reclamo
    return {
        "codreclamo": informe.reclamo,
        "suministro": informe.suministro,
        "clasificacion": r.clasificacion_reclamo if r else None,
        "tipo_reclamo": r.tipo_reclamo if r else None,
        "meses_reclamados": r.meses_reclamados if r else None,
        "periodos_reclamados": [f"{MES_ABREV[m - 1]} {a}" for a, m in periodos_reclamados(r.meses_reclamados if r else None)],
        "fecha_recepcion": _fecha_corta(r.fecha_recepcion) if r else None,
        "veredicto": informe.veredicto,
        "verificaciones": construir_verificaciones(informe),
        "serie": serie,
        "indicadores": indicadores,
        "inspeccion_externa": externa,
        "inspeccion_interna": interna,
        "linea_tiempo": construir_linea_tiempo(informe, indicadores, externa, interna),
        "disponible": {
            "consumo": bool(serie),
            "inspeccion_externa": externa is not None,
            "inspeccion_interna": interna is not None,
        },
        "generado": date.today().isoformat(),
    }
