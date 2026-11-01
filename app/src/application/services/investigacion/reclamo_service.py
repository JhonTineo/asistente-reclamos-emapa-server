"""Utilidades para leer el JSON crudo del reclamo que devuelve EMAPA.

Sus nombres de campo son inconsistentes (camelCase, abreviaturas, mayúsculas
sin patrón: `dniCliente`, `desCodReclamo`, `mesanio`...) y algunos vienen
anidados (las inspecciones, como lista de eventos). Estas funciones normalizan
eso a valores simples y confiables (nunca `None`, nunca explotan con
`KeyError`/`AttributeError`), para que el resto de la app no tenga que conocer
la forma del JSON de EMAPA ni repetir ese manejo defensivo en cada punto que
lee un dato del reclamo.
"""


def campo_reclamo(datos: dict | None, campo: str) -> str:
    """Lee un campo escalar del JSON del reclamo (data puede ser dict o lista)."""
    data = datos.get("data") if isinstance(datos, dict) else None
    if isinstance(data, dict):
        return str(data.get(campo) or "").strip()
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get(campo) or "").strip()
    return ""


def codigo_inspeccion(datos: dict | None, campo: str) -> str | None:
    """Extrae el nroinspeccion del ÚLTIMO item de 'inspeccion_interna' o
    'inspeccion_externa' embebidos en el detalle del reclamo (campo=uno de esos
    dos nombres). NO se usan los demás datos de esos items (podrían estar
    incompletos si la inspección se creó pero aún no se completó): solo sirven
    para obtener el código con el que luego se consulta la inspección fresca y
    completa. None si el reclamo no tiene ninguna inspección de ese tipo
    vinculada todavía."""
    data = datos.get("data") if isinstance(datos, dict) else None
    if isinstance(data, dict):
        codigo_directo = data.get(f"cod{campo}")
        if codigo_directo:
            return str(codigo_directo)
    items = data.get(campo) if isinstance(data, dict) else None
    if isinstance(items, list) and items:
        ultimo = items[-1]
        if isinstance(ultimo, dict) and ultimo.get("nroinspeccion") is not None:
            return str(ultimo["nroinspeccion"])
    return None
