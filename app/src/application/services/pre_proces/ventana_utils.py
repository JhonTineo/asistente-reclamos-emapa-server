"""Cálculo de la ventana de meses de análisis (compartido por todos los
preprocesamientos: tarjeta, record, corte-reapertura, saldo-detalle).

Es una ventana puramente CALENDARIO: los últimos `meses` meses terminando en
`fecha_ref` (la fecha de recepción del reclamo). NO depende de qué datos trae
cada medio, por eso cada preprocesamiento la calcula de forma independiente a
partir de (meses, fecha_ref) — no hace falta que un medio la calcule primero y
se la pase a los demás (ese acoplamiento por orden de llamada causaba que, si
record_facturacion se analizaba antes que tarjeta_lectura, no hubiera ventana
y se devolviera el histórico completo sin filtrar)."""

import re
from datetime import date


def parse_anio_mes(fecha_ref: str | None) -> tuple[int, int] | None:
    """Extrae (año, mes) de la fecha de recepción del reclamo (fecharec), que
    EMAPA entrega en formato ISO 'AAAA-MM-DD' (p.ej. '2022-12-07').
    Devuelve None si viene vacía o con un formato inesperado."""
    if not fecha_ref:
        return None
    m = re.match(r"\s*(\d{4})-(\d{2})", str(fecha_ref))
    return (int(m.group(1)), int(m.group(2))) if m else None


def calcular_ventana(fecha_ref: str | None, meses: int) -> list[tuple[int, int]]:
    """Últimos `meses` (año, mes) terminando en fecha_ref (inclusive), en orden
    cronológico ascendente. Si fecha_ref no viene o no se puede interpretar, usa
    el mes/año actual como referencia (comportamiento de respaldo)."""
    ref = parse_anio_mes(fecha_ref)
    anio_ref, mes_ref = ref if ref else (date.today().year, date.today().month)

    ventana: list[tuple[int, int]] = []
    anio, mes = anio_ref, mes_ref
    for _ in range(meses):
        ventana.append((anio, mes))
        mes -= 1
        if mes == 0:
            mes = 12
            anio -= 1
    ventana.reverse()
    return ventana
