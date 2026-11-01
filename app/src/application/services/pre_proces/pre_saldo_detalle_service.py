import time
import logging
from dataclasses import fields
from typing import get_args, get_type_hints

import pandas as pd

from app.src.core.model.saldo_detalle import SaldoDetalle, SaldoMensual
from app.src.application.ports.emapa_api_port import PuertoEmapaAPI
from app.src.application.services.pre_proces.df_utils import df_a_registros
from app.src.application.services.pre_proces.ventana_utils import calcular_ventana


logger = logging.getLogger("services.pre_saldo_detalle_service")

# Estado de saldo del origen: "001" = mes pagado. Cualquier otro => pendiente.
ESTADO_SALDO_PAGADO = "001"

# El JSON trae 'des_tiposervicio' pero la entidad lo guarda como 'tiposervicio'.
CAMPO_TIPOSERVICIO_JSON = "des_tiposervicio"

COLUMNAS = [f.name for f in fields(SaldoMensual)]
_HINTS = get_type_hints(SaldoMensual)
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


def _tiene_desague(tiposervicio: str | None) -> bool:
    """El servicio incluye alcantarillado/desagüe."""
    t = (tiposervicio or "").upper()
    return "DESAGUE" in t or "DESAGÜE" in t or "ALCANTARILLADO" in t


class PreSaldoDetalleService:
    """Preprocesa el saldo-detalle (pagos por mes) y lo filtra por la ventana de
    meses fijada por la tarjeta de lecturas. Detecta tres tipos de problema:
    cobro indebido (importe por servicio no prestado), cobro de mora y meses no
    pagados. La entidad guarda SOLO los errores hallados (no el detalle mensual)."""

    def __init__(self, emapa_api: PuertoEmapaAPI):
        self.emapa_api = emapa_api

    def preprocesar_saldo_detalle(
        self,
        codsuc: str,
        codcliente: str,
        meses: int = 12,
        fecha_ref: str | None = None,
    ) -> dict:
        t1 = time.time()
        # "Saldo actual" en EMAPA devuelve la deuda vigente a la fecha de
        # consulta, sin importar "fecha_ref" (la API no soporta fecha
        # histórica). La ventana se usa solo para filtrar los recibos del
        # histórico devuelto.
        ventana = calcular_ventana(fecha_ref, meses)

        json_raw = self.emapa_api.obtener_saldo_actual(codsuc, codcliente)
        logger.info("[PRE_SALDO_DETALLE] Datos obtenidos de EMAPA en %.2f s", time.time() - t1)

        saldo, df = self._construir_saldo(json_raw, ventana)

        logger.info(
            "[PRE_SALDO_DETALLE] Preprocesamiento completo en %.2f s | meses=%d | ventana=%d",
            time.time() - t1, saldo.totalMeses, len(ventana),
        )
        return {"saldo": saldo, "df": df}

    def _construir_saldo(
        self, json_raw: dict, ventana: list[tuple[int, int]],
    ) -> tuple[SaldoDetalle, pd.DataFrame]:
        registros = (json_raw or {}).get("data") or []
        if not registros:
            logger.warning("[PRE_SALDO_DETALLE] JSON sin registros en 'data'")
            return SaldoDetalle(), pd.DataFrame(columns=COLUMNAS)

        df_raw = pd.DataFrame(registros)

        # Renombra el tipo de servicio del JSON al nombre de la entidad.
        if CAMPO_TIPOSERVICIO_JSON in df_raw.columns:
            df_raw = df_raw.rename(columns={CAMPO_TIPOSERVICIO_JSON: "tiposervicio"})

        # 1. Tipar año/mes y filtrar por la ventana (inner join).
        df = df_raw.copy()
        df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
        df["mes"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int64")
        if ventana:
            ventana_df = pd.DataFrame(ventana, columns=["anio", "mes"]).astype("Int64")
            df = df.merge(ventana_df, on=["anio", "mes"], how="inner")
        logger.info("[PRE_SALDO_DETALLE] Meses en la ventana: %d", len(df))

        # 2. Limpieza: conservar columnas relevantes y tipar numéricos.
        df = df[[c for c in COLUMNAS if c in df.columns]].copy()
        for col in CAMPOS_NUMERICOS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Float64")
        df = df.sort_values(["anio", "mes"]).reset_index(drop=True)

        indicadores = self._calcular_indicadores(df)
        tipo_servicio = None
        if "tiposervicio" in df.columns and df["tiposervicio"].notna().any():
            tipo_servicio = str(df["tiposervicio"].dropna().mode().iloc[0])
        saldo = SaldoDetalle(
            tipoServicio=tipo_servicio, registros=df_a_registros(df), **indicadores
        )
        return saldo, df

    def _calcular_indicadores(self, df: pd.DataFrame) -> dict:
        """Filtra con pandas solo los meses "con problema" (no todo el detalle
        mensual, para no sobrecargar el prompt del LLM):

        - cobroIndebido: se cobra alcantarillado (impmesalc > 0) cuando el tipo
          de servicio no incluye desagüe/alcantarillado.
        - mora: impmesmora > 0 e imptotal > impmestotal (se suma la mora al
          importe del mes).
        - mesesNoPagados: meses con estadosaldo distinto de 001 anteriores al
          mes anterior (el mes anterior se paga en el mes actual, no cuenta)."""
        d = df.dropna(subset=["anio", "mes"]).copy()
        if d.empty:
            return {"totalMeses": 0, "cobroIndebido": [], "mora": [], "mesesNoPagados": []}

        d = d.sort_values(["anio", "mes"]).reset_index(drop=True)
        d["estadosaldo"] = d["estadosaldo"].astype("string").str.strip()

        # --- Cobro indebido: alcantarillado sin servicio de desagüe -----------
        cobro_indebido: list[str] = []
        d["_tieneDesague"] = d["tiposervicio"].apply(_tiene_desague)
        d["_alc"] = pd.to_numeric(d["impmesalc"], errors="coerce").fillna(0)
        indebido = list(
            d.loc[(~d["_tieneDesague"]) & (d["_alc"] > 0), ["anio", "mes"]]
            .astype(int).itertuples(index=False, name=None)
        )
        if indebido:
            cobro_indebido.append(
                "Se cobró importe por alcantarillado sin que el suministro cuente "
                f"con ese servicio en {_listar_meses(indebido)}."
            )

        # --- Mora: se cobra mora además del importe del mes -------------------
        mora: list[str] = []
        d["_mora"] = pd.to_numeric(d["impmesmora"], errors="coerce").fillna(0)
        d["_total"] = pd.to_numeric(d["imptotal"], errors="coerce").fillna(0)
        d["_mestotal"] = pd.to_numeric(d["impmestotal"], errors="coerce").fillna(0)
        con_mora = list(
            d.loc[(d["_mora"] > 0) & (d["_total"] > d["_mestotal"]), ["anio", "mes"]]
            .astype(int).itertuples(index=False, name=None)
        )
        if con_mora:
            mora.append(
                f"Se cobró mora además del importe del mes en {_listar_meses(con_mora)}."
            )

        # --- Meses no pagados: pendientes anteriores al mes anterior ----------
        # El último mes de la ventana es el mes actual; el anterior se paga en el
        # actual, así que solo son problema los pendientes previos a ese.
        meses_no_pagados: list[str] = []
        meses_ordenados = list(
            d[["anio", "mes"]].astype(int).itertuples(index=False, name=None)
        )
        # Todo lo anterior al penúltimo mes (excluye mes actual y mes anterior).
        limite = meses_ordenados[:-2]
        pendientes_pares = set(limite)
        pendientes = list(
            d.loc[
                (d["estadosaldo"] != ESTADO_SALDO_PAGADO)
                & d[["anio", "mes"]].astype(int).apply(tuple, axis=1).isin(pendientes_pares),
                ["anio", "mes"],
            ].astype(int).itertuples(index=False, name=None)
        )
        if pendientes:
            meses_no_pagados.append(
                f"Hay meses con saldo pendiente de pago en {_listar_meses(pendientes)}."
            )

        return {
            "totalMeses": int(len(d)),
            "cobroIndebido": cobro_indebido,
            "mora": mora,
            "mesesNoPagados": meses_no_pagados,
        }
