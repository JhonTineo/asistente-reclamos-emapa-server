"""Utilidades compartidas por los servicios de preprocesamiento."""

import pandas as pd


def df_a_registros(df: pd.DataFrame) -> list[dict]:
    """Convierte un DataFrame (con dtypes nullable Int64/Float64) a una lista
    de dicts apta para JSON: NaN/pd.NA se convierten a None (NaN no es JSON
    válido y rompe el parseo en el frontend)."""
    return df.astype(object).where(pd.notnull(df), None).to_dict("records")
