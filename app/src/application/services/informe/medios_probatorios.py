"""Selección determinista de medios probatorios por tipo de reclamo."""

from typing import TypedDict


class MedioProbatorio(TypedDict):
    id: str
    nombre: str


_MEDIOS_POR_TIPO_RECLAMO: dict[str, tuple[MedioProbatorio, ...]] = {
    "001": (
        {"id": "inspeccion_externa", "nombre": "Inspección Externa"},
        {"id": "inspeccion_interna", "nombre": "Inspección Interna"},
        {"id": "record_facturacion", "nombre": "Récord de Facturación"},
        {"id": "tarjeta_lectura", "nombre": "Tarjeta de Lectura"},
        {"id": "corte_reapertura", "nombre": "Corte y Reapertura"},
        {"id": "saldo_detalle", "nombre": "Saldo Detalle"},
    ),
}


def obtener_medios_probatorios(codigo_tipo_reclamo: str | None) -> list[MedioProbatorio]:
    """Devuelve copias de los medios aplicables al código de tipo recibido."""
    codigo = (codigo_tipo_reclamo or "").strip().zfill(3)
    return [dict(medio) for medio in _MEDIOS_POR_TIPO_RECLAMO.get(codigo, ())]
