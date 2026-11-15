"""Constataciones: hechos neutros o favorables que se verifican por reglas.

Los problemas (``problemas_normalizer``) solo registran anomalías. Sin
constataciones, la evidencia que sostiene un INFUNDADO ("el mes reclamado se
facturó por lectura real", "el medidor funciona", "no se pudo inspeccionar el
interior") no existe como hecho, y los pasos que siguen (resumen, evaluación,
fundamentación) la ignoran o la inventan.

Reglas de redacción de cada constatación:
- Una oración autosuficiente, con cifras y unidades, lista para el informe.
- Sin ":" en el texto: la búsqueda normativa toma lo que va antes de ":" como
  concepto, y aquí el concepto lo aporta el ``tipo``.
- Solo afirma lo que el dato muestra; nunca atribuye una causa.

Funciona sobre ``asdict(entidad)`` (el ``entidad`` del bloque), así sirve igual
para un análisis nuevo y para un informe rehidratado o recargado de la BD.
"""

import logging
import re
from datetime import date, datetime

from app.src.core.model.informe_atencion import ProblemaNormado

logger = logging.getLogger("services.constataciones")

# Hechos que LIMITAN lo que se pudo verificar. Deben acompañar siempre a la
# fundamentación y a la conclusión: si se omiten, los hechos favorables de la
# inspección externa terminan generalizándose al interior del predio.
LIMITACIONES = frozenset({
    "inspeccionInternaSinAcceso",
    "sinLecturaMesReclamado",
    "sinFacturacionMesReclamado",
})

# Hechos del mes en disputa: núcleo de todo reclamo de consumo. Son candidatos
# a fundamentar aunque su medio no sea el de un objetivo determinante.
HECHOS_MES_RECLAMADO = frozenset({
    "lecturaMesReclamado",
    "facturacionMesReclamado",
    "sinLecturaMesReclamado",
    "sinFacturacionMesReclamado",
})

# Periodo válido entre lecturas para facturar por diferencia de lecturas
# (Reglamento de Calidad SUNASS, art. 91 inciso f).
DIAS_LECTURA_MIN, DIAS_LECTURA_MAX = 28, 32

MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "setiembre", "octubre", "noviembre", "diciembre",
)

# Patrones del inspector que indican que NO se ingresó al predio, con la razón
# que se cita en el informe. El orden importa: la primera coincidencia gana.
_SIN_ACCESO = [
    (r"NO\s+HUBO\s+RESPUESTA|NO\s+RESPONDI", "no hubo respuesta del usuario"),
    (r"NO\s+PERMITI|NEG[OÓ]\s+(EL\s+)?(INGRESO|ACCESO)", "el usuario no permitió el ingreso"),
    (r"AUSENTE|NO\s+SE\s+ENCONTR[OÓ]\s+(AL\s+)?(USUARIO|NADIE)|NADIE", "no se encontró al usuario en el predio"),
    (r"CERRAD[OA]", "el predio estaba cerrado"),
    (r"NO\s+SE\s+PUDO\s+(INGRESAR|REALIZAR|ACCEDER)", "no se pudo ingresar al predio"),
    (r"SE\s+REALIZ[OÓ]\s+(SOLO\s+)?INSPECCI[OÓ]N\s+EXTERNA", "solo se realizó la inspección externa"),
]


# --------------------------------------------------------------------------- #
# Utilidades de formato
# --------------------------------------------------------------------------- #
def nombre_mes(anio: int, mes: int) -> str:
    return f"{MESES[mes - 1]} de {anio}"


def _periodo(anio: int, mes: int) -> str:
    return f"{anio:04d}-{mes:02d}"


def _num(valor) -> float | None:
    try:
        return None if valor is None or valor == "" else float(valor)
    except (TypeError, ValueError):
        return None


def _m3(valor: float) -> str:
    return f"{valor:.0f} m³" if float(valor).is_integer() else f"{valor:.1f} m³"


def _soles(valor: float) -> str:
    return f"S/ {valor:,.2f}"


def _fecha(texto) -> str | None:
    """'2026-10-19' o '2026-09-16 00:00:00.0' -> '19/10/2026'."""
    if not texto:
        return None
    try:
        return datetime.fromisoformat(str(texto).strip()[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(texto)


def _fecha_obj(texto) -> date | None:
    try:
        return datetime.fromisoformat(str(texto).strip()[:10]).date() if texto else None
    except ValueError:
        return None


def _oracion(texto: str) -> str:
    """'El medidor funciona correctamente.' -> 'el medidor funciona correctamente'."""
    t = (texto or "").strip().rstrip(".")
    return t[:1].lower() + t[1:] if t else t


def _fila(registros: list[dict], anio: int, mes: int) -> dict | None:
    for r in registros or []:
        try:
            if int(r.get("anio")) == anio and int(r.get("mes")) == mes:
                return r
        except (TypeError, ValueError):
            continue
    return None


def _ordenados(registros: list[dict]) -> list[dict]:
    validos = []
    for r in registros or []:
        try:
            validos.append(((int(r["anio"]), int(r["mes"])), r))
        except (KeyError, TypeError, ValueError):
            continue
    return [r for _, r in sorted(validos, key=lambda x: x[0])]


def _hecho(tipo: str, detalle: str, *, periodo: str | None = None, valor: dict | None = None,
           fuente: str | None = None, texto_original: str | None = None) -> ProblemaNormado:
    return ProblemaNormado(
        tipo=tipo, detalle=detalle, fuente=fuente, texto_original=texto_original,
        clase="constatacion", periodo=periodo, valor=valor,
    )


# --------------------------------------------------------------------------- #
# Reglas por medio
# --------------------------------------------------------------------------- #
CODIGO_CONSUMO_ATIPICO = "008"


def _marca_atipico(fila: dict) -> bool:
    codigo = str(fila.get("estadolectura") or "").strip()
    texto = (fila.get("desestadolectura") or fila.get("estadolectura_texto") or "").upper()
    return codigo == CODIGO_CONSUMO_ATIPICO or "ATIPICO" in texto or "ATÍPICO" in texto


def _supera_doble(fila: dict) -> bool:
    consumo, promedio = _num(fila.get("consumo")), _num(fila.get("lecturapromedio"))
    return bool(consumo is not None and promedio and consumo > 2 * promedio)


def _es_atipico(fila: dict) -> bool:
    return _marca_atipico(fila) or _supera_doble(fila)


def _racha_atipica(registros: list[dict], pos: int) -> tuple[int, bool]:
    """Meses atípicos consecutivos que terminan en ``pos`` (0 si ese mes no lo
    es) y si hubo otro episodio atípico en los 12 meses anteriores a la racha
    (RC Art. 92.3: el promedio solo procede una vez cada 12 meses y como máximo
    por 2 meses consecutivos)."""
    consecutivos = 0
    i = pos
    while i >= 0 and _es_atipico(registros[i]):
        consecutivos += 1
        i -= 1
    inicio_racha = pos - consecutivos + 1
    previos = registros[max(0, inicio_racha - 12):max(0, inicio_racha)]
    return consecutivos, any(_es_atipico(r) for r in previos) if consecutivos else False


def _tarjeta_lectura(datos: dict, periodos: list[tuple[int, int]]) -> list[ProblemaNormado]:
    hechos: list[ProblemaNormado] = []
    registros = _ordenados(datos.get("registros") or [])

    for anio, mes in periodos:
        fila = _fila(registros, anio, mes)
        if fila is None:
            hechos.append(_hecho(
                "sinLecturaMesReclamado",
                f"La tarjeta de lecturas no tiene registro de lectura para {nombre_mes(anio, mes)}.",
                periodo=_periodo(anio, mes), fuente="tarjeta_lectura.registros",
            ))
            continue
        consumo = _num(fila.get("consumo"))
        promedio = _num(fila.get("lecturapromedio"))
        anterior, ultima = _num(fila.get("lecturaanterior")), _num(fila.get("lecturaultima"))
        estado = (fila.get("desestadolectura") or fila.get("estadolectura_texto") or "").strip()
        medidor = (fila.get("desestadomed") or fila.get("estadomed_texto") or "").strip()
        partes = [f"En {nombre_mes(anio, mes)} se registró"]
        if anterior is not None and ultima is not None:
            partes.append(f"una lectura de {anterior:.0f} a {ultima:.0f}")
            fecha = _fecha(fila.get("fechalecturault"))
            if fecha:
                partes.append(f"el {fecha}")
        texto = " ".join(partes)
        if consumo is not None:
            texto += f", con un consumo de {_m3(consumo)}"
            if promedio:
                texto += (f" frente a un promedio de {_m3(promedio)} "
                          f"({consumo / promedio:.1f} veces el promedio)")
        if estado and medidor:
            texto += f"; la lectura figura como {estado.lower()} y el medidor en {medidor.lower()}"
        elif estado:
            texto += f"; la lectura figura como {estado.lower()}"
        elif medidor:
            texto += f"; el medidor figura en {medidor.lower()}"

        # Días entre esta lectura y la del mes anterior: sin este dato, la
        # validez de la diferencia de lecturas (28 a 32 días) solo se puede
        # citar como condición, no como hecho comprobado.
        pos = registros.index(fila)
        dias = None
        if pos > 0:
            actual = _fecha_obj(fila.get("fechalecturault"))
            previa = _fecha_obj(registros[pos - 1].get("fechalecturault"))
            if actual and previa and actual > previa:
                dias = (actual - previa).days
                rango = (
                    "dentro" if DIAS_LECTURA_MIN <= dias <= DIAS_LECTURA_MAX else "fuera"
                )
                texto += (f". Entre la lectura anterior ({previa:%d/%m/%Y}) y esta "
                          f"transcurrieron {dias} días, {rango} del periodo de "
                          f"{DIAS_LECTURA_MIN} a {DIAS_LECTURA_MAX} días")
        # Atípico (RC Art. 92.1): se registra la parte calculable (supera en más
        # del 100% al promedio) y la marca del propio sistema de EMAPA. La otra
        # condición (al menos 2 asignaciones de consumo) requiere la tabla de
        # asignaciones, que aún no está en los datos.
        atipico = _es_atipico(fila)
        consecutivos, episodio_previo = _racha_atipica(registros, pos)
        if atipico:
            texto += (". Es un consumo atípico ("
                      + ("supera en más del 100% al promedio" if _supera_doble(fila)
                         else "figura como consumo atípico en el sistema")
                      + (f"; {consecutivos} meses atípicos consecutivos" if consecutivos > 1 else "")
                      + (", con otro episodio atípico en los 12 meses anteriores" if episodio_previo else "")
                      + ")")
        hechos.append(_hecho(
            "lecturaMesReclamado", texto + ".",
            periodo=_periodo(anio, mes), fuente="tarjeta_lectura.registros",
            valor={"consumo_m3": consumo, "promedio_m3": promedio, "lectura_anterior": anterior,
                   "lectura_ultima": ultima, "estado_lectura": estado or None,
                   "estado_medidor": medidor or None, "dias_entre_lecturas": dias,
                   "veces_promedio": round(consumo / promedio, 2) if consumo is not None and promedio else None,
                   "supera_100_pct": _supera_doble(fila),
                   "marca_atipico_emapa": _marca_atipico(fila),
                   "atipico": atipico,
                   "meses_atipicos_consecutivos": consecutivos,
                   "episodio_atipico_previo_12m": episodio_previo},
        ))

        # Tendencia: los 3 meses previos y el reclamado con consumo creciente.
        tramo = registros[max(0, pos - 3): pos + 1]
        consumos = [_num(r.get("consumo")) for r in tramo]
        if (len(tramo) == 4 and None not in consumos
                and all(a < b for a, b in zip(consumos, consumos[1:]))):
            inicio = tramo[0]
            cifras = ", ".join(f"{c:.0f}" for c in consumos[:-1]) + f" y {consumos[-1]:.0f} m³"
            hechos.append(_hecho(
                "tendenciaCreciente",
                f"El consumo aumentó de forma sostenida desde "
                f"{nombre_mes(int(inicio['anio']), int(inicio['mes']))} hasta "
                f"{nombre_mes(anio, mes)} ({cifras}).",
                periodo=_periodo(anio, mes), fuente="tarjeta_lectura.registros",
                valor={"consumos_m3": consumos},
            ))

    # Medidor instalado en los 12 meses anteriores al primer mes reclamado.
    instalado = _fecha_obj(datos.get("fecha_instalacion_medidor"))
    if instalado and periodos:
        anio, mes = periodos[0]
        meses_desde = (anio - instalado.year) * 12 + (mes - instalado.month)
        if 0 <= meses_desde <= 12:
            nro = (datos.get("nro_medidor") or "").strip()
            hechos.append(_hecho(
                "medidorReciente",
                f"El medidor{(' N.º ' + nro) if nro else ''} fue instalado el "
                f"{instalado:%d/%m/%Y}, {meses_desde} meses antes de {nombre_mes(anio, mes)}.",
                fuente="tarjeta_lectura.fecha_instalacion_medidor",
                valor={"nro_medidor": nro or None, "fecha_instalacion": instalado.isoformat()},
            ))
    return hechos


def _record_facturacion(datos: dict, periodos: list[tuple[int, int]]) -> list[ProblemaNormado]:
    hechos: list[ProblemaNormado] = []
    registros = _ordenados(datos.get("registros") or [])

    for anio, mes in periodos:
        fila = _fila(registros, anio, mes)
        if fila is None:
            hechos.append(_hecho(
                "sinFacturacionMesReclamado",
                f"El récord de facturación no tiene registro para {nombre_mes(anio, mes)}.",
                periodo=_periodo(anio, mes), fuente="record_facturacion.registros",
            ))
            continue
        forma = (fila.get("tipopromedio_texto") or "").strip().upper()
        consumo = _num(fila.get("consumofac") if fila.get("consumofac") is not None else fila.get("consumo"))
        importe = _num(fila.get("impmestotal"))
        if forma == "MEDIDO":
            como = "por la lectura del medidor"
        elif forma:
            como = f"por promedio ({forma.lower()})"
        else:
            como = "sin indicar el tipo de facturación"
        texto = f"En {nombre_mes(anio, mes)} se facturó {como}"
        if consumo is not None:
            texto += f", con un consumo de {_m3(consumo)}"
        if importe is not None:
            texto += f" y un importe de {_soles(importe)}"
        hechos.append(_hecho(
            "facturacionMesReclamado", texto + ".",
            periodo=_periodo(anio, mes), fuente="record_facturacion.registros",
            valor={"forma": forma or None, "consumo_m3": consumo, "importe": importe},
        ))

    for fila in registros:
        rebaja = _num(fila.get("c_impmesrebaja"))
        if not rebaja:
            continue
        anio, mes = int(fila["anio"]), int(fila["mes"])
        fecha = _fecha(fila.get("c_diarebaja"))
        hechos.append(_hecho(
            "rebajaAplicada",
            f"Al recibo de {nombre_mes(anio, mes)} se le aplicó una rebaja de {_soles(rebaja)}"
            + (f", registrada el {fecha}" if fecha else "") + ".",
            periodo=_periodo(anio, mes), fuente="record_facturacion.c_impmesrebaja",
            valor={"rebaja": rebaja, "fecha": fecha},
        ))
    return hechos


def _inspeccion_externa(datos: dict) -> list[ProblemaNormado]:
    if not datos.get("nroinspeccion"):
        return []
    fecha = _fecha(datos.get("fechainspeccion"))
    en = f"En la inspección externa del {fecha}" if fecha else "En la inspección externa"
    hechos: list[ProblemaNormado] = []

    funcionamiento = (datos.get("funcionamed") or "").strip()
    if funcionamiento:
        obs = (datos.get("observacionmed") or "").strip()
        hechos.append(_hecho(
            "estadoMedidorInspeccion",
            f"{en}, {_oracion(funcionamiento)}"
            + (f" (observación del inspector, {obs.lower()})" if obs else "") + ".",
            fuente="inspeccion_externa.funcionamed", texto_original=obs or None,
        ))
    fugas = (datos.get("fugas") or "").strip()
    if fugas:
        tipo_fuga = (datos.get("tipofugas") or "").strip()
        detalle_tipo = (f" (tipo {tipo_fuga.lower()})"
                        if tipo_fuga and tipo_fuga.lower() not in ("no hay", "ninguna") else "")
        # Dónde está la fuga decide de quién es la responsabilidad (RC Art. 8.2:
        # la empresa responde hasta la conexión domiciliaria, caja incluida).
        tipo_norm = tipo_fuga.lower()
        ubicacion = ("caja" if "caja" in tipo_norm else
                     "antes_medidor" if "antes del medidor" in tipo_norm else
                     "despues_medidor" if "despues del medidor" in tipo_norm
                     or "después del medidor" in tipo_norm else None)
        # Ojo: "No se detectaron fugas" contiene "se detectaron fugas"; se mira
        # el inicio de la frase traducida (ver INDICADORES_INSPECCION_EXTERNA).
        hay_fuga = fugas.lower().startswith("se detectaron fugas") or ubicacion is not None
        hechos.append(_hecho(
            "fugasInspeccionExterna", f"{en}, {_oracion(fugas)}{detalle_tipo}.",
            fuente="inspeccion_externa.fugas",
            valor={"hay_fuga": hay_fuga, "ubicacion": ubicacion},
        ))
    estados = [_oracion(t) for t in (datos.get("estadocaja"), datos.get("estconexion")) if t]
    if estados:
        hechos.append(_hecho(
            "estadoConexionInspeccion", f"{en}, {' y '.join(estados)}.",
            fuente="inspeccion_externa.estadocaja",
        ))
    return hechos


def _inspeccion_interna(datos: dict) -> list[ProblemaNormado]:
    if not datos.get("nroinspeccion"):
        return []
    fecha = _fecha(datos.get("fechainspeccion"))
    el = f"El {fecha}" if fecha else "En la inspección interna"
    puntos = datos.get("puntos_agua") or []
    if puntos:
        total = sum(
            int(v) for p in puntos if isinstance(p, dict)
            for v in p.values() if isinstance(v, (int, float))
        )
        return [_hecho(
            "inspeccionInternaRealizada",
            f"{el} se inspeccionaron las instalaciones internas del predio"
            + (f" ({total} puntos de agua registrados)" if total else "") + ".",
            fuente="inspeccion_interna.puntos_agua", valor={"puntos_agua": total},
        )]
    obs = " ".join(
        (datos.get(campo) or "").strip()
        for campo in ("obsinsinteriores", "observaciones", "obsperrepins")
    ).strip()
    obs_mayus = obs.upper()
    for patron, razon in _SIN_ACCESO:
        if re.search(patron, obs_mayus):
            return [_hecho(
                "inspeccionInternaSinAcceso",
                f"{el} no se pudo inspeccionar el interior del predio porque {razon}.",
                fuente="inspeccion_interna.obsinsinteriores", texto_original=obs,
                # Quién causó que no se hiciera decide el caso (RC Art. 92.4,
                # RGR Art. 14.4-14.6). Solo una negativa explícita se atribuye
                # al usuario; una ausencia depende de si fue bien notificado.
                valor={"razon": razon,
                       "causa": "usuario" if "no permitió" in razon else "no_determinada"},
            )]
    return []


def _corte_reapertura(datos: dict) -> list[ProblemaNormado]:
    total = int(_num(datos.get("totalProrrogas")) or 0)
    if total <= 0:
        return []
    meses = []
    for entrada in datos.get("prorrogas") or []:
        m = re.match(r"(\d{4})-(\d{2})", str(entrada))
        if m:
            texto = f"{m.group(2)}/{m.group(1)}"
            if texto not in meses:
                meses.append(texto)
    return [_hecho(
        "prorrogasCorte",
        f"Se registraron {total} prórroga{'s' if total != 1 else ''} de corte del servicio"
        + (f" ({', '.join(meses)})" if meses else "") + ".",
        fuente="corte_reapertura.prorrogas", valor={"total": total, "meses": meses},
    )]


def extraer_constataciones(
    medio_id: str, datos: dict | None, periodos: list[tuple[int, int]] | None = None,
) -> list[ProblemaNormado]:
    """Constataciones del medio a partir de sus datos (``asdict`` de la entidad)
    y de los meses reclamados ``[(anio, mes)]``."""
    datos = datos or {}
    periodos = sorted(set(periodos or []))
    if medio_id == "tarjeta_lectura":
        return _tarjeta_lectura(datos, periodos)
    if medio_id == "record_facturacion":
        return _record_facturacion(datos, periodos)
    if medio_id == "inspeccion_externa":
        return _inspeccion_externa(datos)
    if medio_id == "inspeccion_interna":
        return _inspeccion_interna(datos)
    if medio_id == "corte_reapertura":
        return _corte_reapertura(datos)
    # saldo_detalle: falta confirmar el significado de sus registros
    # (estadosaldo) antes de afirmar si hay o no deuda.
    return []


def constatar(
    medio_id: str, datos: dict | None, periodos: list[tuple[int, int]] | None = None,
) -> list[ProblemaNormado]:
    """Como ``extraer_constataciones``, pero nunca interrumpe el análisis: si
    una regla falla con datos inesperados, el medio sigue sin constataciones."""
    try:
        return extraer_constataciones(medio_id, datos, periodos)
    except Exception:  # noqa: BLE001
        logger.exception("[CONSTATACIONES] Falló la extracción para %s", medio_id)
        return []
