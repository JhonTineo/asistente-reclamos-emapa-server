import time
import logging
from datetime import datetime
from dataclasses import fields
from typing import get_args, get_type_hints

import pandas as pd

from app.src.core.model.record_facturacion import RecordFacturacion, RegistroFacturacion
from app.src.core.model.indicadores.targeta_lecturas_indicadores import INDICADORES_TARJETA_LECTURA
from app.src.application.adapters.emapa_api import obtener_record_facturacion
from app.src.application.services.pre_proces.df_utils import df_a_registros


logger = logging.getLogger("services.pre_record_facturacion_service")

# Forma de facturación por código tipopromedio (reutiliza el dominio de la tarjeta).
FORMAS = INDICADORES_TARJETA_LECTURA["tipopromedio"]  # {"0": "MEDIDO", "1": "ASIGNADO", "2": "PROMEDIADO"}
TIPO_MEDIDO = "0"  # facturado por lectura real

COLUMNAS = [f.name for f in fields(RegistroFacturacion)]
_HINTS = get_type_hints(RegistroFacturacion)
CAMPOS_NUMERICOS = [n for n, t in _HINTS.items() if float in get_args(t) or t is float]

MESES_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _mes_anio(anio: int, mes: int) -> str:
    return f"{MESES_ES[mes - 1]} de {anio}"


def _listar_meses(meses: list[tuple[int, int]]) -> str:
    """[(2025,1), (2025,3)] -> 'enero de 2025 y marzo de 2025'."""
    textos = [_mes_anio(a, m) for a, m in meses]
    if len(textos) == 1:
        return textos[0]
    return f"{', '.join(textos[:-1])} y {textos[-1]}"


class PreRecordFacturacionService:
    """Preprocesa el record de facturación y lo filtra por la ventana de meses
    fijada por la tarjeta de lecturas. Lo relevante es cómo se facturó cada mes
    (por lectura=MEDIDO o por promedio): facturar por promedio varios meses y
    luego cobrar por lectura suele originar el reclamo, sin responsabilidad de la
    empresa. La entidad guarda SOLO los errores hallados (no el detalle mensual)."""

    def preprocesar_record_facturacion(
        self, codsuc: str, codcliente: str,
        ventana: list[tuple[int, int]] | None = None,
    ) -> dict:
        t1 = time.time()
        ventana = ventana or []
        if not ventana:
            logger.warning(
                "[PRE_RECORD_FACTURACION] Sin ventana fijada: analiza primero la tarjeta de lecturas"
            )
        # El endpoint pide un año; el origen devuelve el histórico completo, así
        # que basta con el año más reciente de la ventana (o el año actual).
        anio = str(max((a for a, _ in ventana), default=datetime.now().year))

        json_raw = obtener_record_facturacion(codsuc, codcliente, anio)
        logger.info("[PRE_RECORD_FACTURACION] Datos obtenidos de EMAPA en %.2f s", time.time() - t1)

        record, df = self._construir_record(json_raw, ventana)

        logger.info(
            "[PRE_RECORD_FACTURACION] Preprocesamiento completo en %.2f s | meses=%d | promediados=%d | ventana=%d",
            time.time() - t1, record.totalMeses, record.totalPromediados, len(ventana),
        )
        return {"record": record, "df": df}

    def _construir_record(
        self, json_raw: dict, ventana: list[tuple[int, int]],
    ) -> tuple[RecordFacturacion, pd.DataFrame]:
        registros = (json_raw or {}).get("data") or []
        if not registros:
            logger.warning("[PRE_RECORD_FACTURACION] JSON sin registros en 'data'")
            return RecordFacturacion(), pd.DataFrame(columns=COLUMNAS)

        df_raw = pd.DataFrame(registros)
        codcliente = str(df_raw["codcliente"].iloc[0]) if "codcliente" in df_raw.columns else None

        # 1. Tipar año/mes y filtrar por la ventana (inner join).
        df = df_raw.copy()
        df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
        df["mes"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int64")
        if ventana:
            ventana_df = pd.DataFrame(ventana, columns=["anio", "mes"]).astype("Int64")
            df = df.merge(ventana_df, on=["anio", "mes"], how="inner")
        logger.info("[PRE_RECORD_FACTURACION] Meses en la ventana: %d", len(df))

        # 2. Limpieza: conservar columnas relevantes y tipar numéricos.
        df = df[[c for c in COLUMNAS if c in df.columns]].copy()
        for col in CAMPOS_NUMERICOS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Float64")
        df = df.sort_values(["anio", "mes"]).reset_index(drop=True)

        indicadores = self._calcular_indicadores(df)
        record = RecordFacturacion(codcliente=codcliente, registros=df_a_registros(df), **indicadores)
        return record, df

    def _calcular_indicadores(self, df: pd.DataFrame) -> dict:
        """Filtra con pandas solo los meses "con problema" (no todo el detalle
        mensual, para no sobrecargar el prompt del LLM):

        - mesesPromediados: meses facturados por promedio (no por lectura).
        - rachaPromediados: rachas de meses por promedio que terminan en un mes
          facturado por lectura (suele originar el reclamo)."""
        d = df.dropna(subset=["anio", "mes"]).copy()
        if d.empty:
            return {
                "formaPredominante": None,
                "totalMeses": 0,
                "totalPromediados": 0,
                "mesesPromediados": [],
                "rachaPromediados": [],
            }

        d["tipopromedio"] = d["tipopromedio"].astype(str).str.strip()
        d["esMedido"] = d["tipopromedio"] == TIPO_MEDIDO
        d = d.sort_values(["anio", "mes"]).reset_index(drop=True)

        forma_predominante = FORMAS.get(d["tipopromedio"].mode().iloc[0])

        # --- Meses facturados por promedio (filtro pandas) --------------------
        promediados = list(
            d.loc[~d["esMedido"], ["anio", "mes"]].astype(int).itertuples(index=False, name=None)
        )
        meses_promediados: list[str] = []
        if promediados:
            meses_promediados.append(
                f"Se facturó por promedio los meses de {_listar_meses(promediados)}."
            )

        # --- Rachas de promedio que terminan en un mes por lectura -------------
        racha_promediados: list[str] = []
        racha_actual: list[tuple[int, int]] = []
        for fila in d.itertuples(index=False):
            par = (int(fila.anio), int(fila.mes))
            if not fila.esMedido:
                racha_actual.append(par)
                continue
            if racha_actual:
                racha_promediados.append(
                    f"Los meses {_listar_meses(racha_actual)} fueron facturados por "
                    f"promedio, y el mes de {_mes_anio(*par)} por lectura, lo cual "
                    "suele generar reclamos."
                )
            racha_actual = []

        return {
            "formaPredominante": forma_predominante,
            "totalMeses": int(len(d)),
            "totalPromediados": int((~d["esMedido"]).sum()),
            "mesesPromediados": meses_promediados,
            "rachaPromediados": racha_promediados,
        }
