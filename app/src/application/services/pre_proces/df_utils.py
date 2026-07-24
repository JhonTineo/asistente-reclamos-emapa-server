"""Utilidades compartidas por los servicios de preprocesamiento."""

import pandas as pd


def df_a_registros(df: pd.DataFrame) -> list[dict]:
    """Convierte un DataFrame (con dtypes nullable Int64/Float64) a una lista
    de dicts apta para JSON: NaN/pd.NA se convierten a None (NaN no es JSON
    válido y rompe el parseo en el frontend)."""
    return df.astype(object).where(pd.notnull(df), None).to_dict("records")


def agregar_traducciones(registros: list[dict], columnas: dict[str, dict[str, str]]) -> list[dict]:
    """Añade, por cada fila, un campo hermano '<columna>_texto' con la
    traducción legible del código (usando el mapa de `columnas`), SIN tocar el
    campo original: el front puede seguir mostrando/usando el código crudo (p.ej.
    en un tooltip) y a la vez tener el texto listo para mostrar directamente.

    `columnas` mapea nombre de campo -> {codigo: texto} (los mapas de
    INDICADORES_TARJETA_LECTURA, etc.). Si el código no está en el mapa, el
    campo de texto queda None (no se inventa una traducción)."""
    for r in registros:
        for campo, mapa in columnas.items():
            if campo not in r:
                continue
            valor = r.get(campo)
            r[f"{campo}_texto"] = mapa.get(str(valor)) if valor is not None else None
    return registros
