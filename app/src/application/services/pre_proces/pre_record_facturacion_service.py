import time
import logging
from datetime import datetime
from dataclasses import fields
from typing import get_args, get_type_hints

import pandas as pd

from app.src.core.model.record_facturacion import RecordFacturacion, RegistroFacturacion
from app.src.core.model.indicadores.targeta_lecturas_indicadores import INDICADORES_TARJETA_LECTURA
from app.src.application.ports.emapa_api_port import PuertoEmapaAPI
from app.src.application.services.pre_proces.df_utils import df_a_registros, agregar_traducciones
from app.src.application.services.pre_proces.ventana_utils import calcular_ventana


logger = logging.getLogger("services.pre_record_facturacion_service")

# Forma de facturación por código tipopromedio (reutiliza el dominio de la tarjeta).
FORMAS = INDICADORES_TARJETA_LECTURA["tipopromedio"]  # {"0": "MEDIDO", "1": "ASIGNADO", "2": "PROMEDIADO"}
TIPO_MEDIDO = "0"  # facturado por lectura real
# Categoría tarifaria: código catetar -> nombre (DOMESTICO, COMERCIAL, …).
CATETAR = INDICADORES_TARJETA_LECTURA["catetar"]


def _traducir_categoria(cod) -> str | None:
    """Traduce el código catetar (p.ej. '015' o '15.0') a su nombre."""
    if cod is None:
        return None
    c = str(cod).strip().split(".")[0]
    return CATETAR.get(c) or CATETAR.get(c.zfill(3))

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

    def __init__(self, emapa_api: PuertoEmapaAPI):
        self.emapa_api = emapa_api

    def preprocesar_record_facturacion(
        self, codsuc: str, codcliente: str, meses: int = 12,
        fecha_ref: str | None = None,
    ) -> dict:
        t1 = time.time()
        # Ventana CALENDARIO calculada de antemano (independiente de qué medio se
        # analice primero; ver ventana_utils.py).
        ventana = calcular_ventana(fecha_ref, meses)

        # El endpoint EXIGE un año como parámetro (si no se manda, no responde),
        # pero el origen es inconsistente: devuelve el MISMO histórico completo
        # sin importar qué año se pida. Por eso basta una sola llamada (con
        # cualquier año válido de la ventana, solo para que responda); el
        # histórico completo se filtra después por la ventana calendario.
        anio = str(max((a for a, _ in ventana), default=datetime.now().year))
        json_raw = self.emapa_api.obtener_record_facturacion(codsuc, codcliente, anio)
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
        # Cada fila trae el código crudo (p.ej. tipopromedio="0") y, junto a él,
        # '<campo>_texto' con la traducción legible, para que el frontend pueda
        # mostrar el texto y, si quiere, el código original.
        registros = agregar_traducciones(df_a_registros(df), {
            "tipopromedio": FORMAS,
            "catetar": CATETAR,
            "estadoservicio": INDICADORES_TARJETA_LECTURA["estadoservicio"],
        })
        record = RecordFacturacion(registros=registros, **indicadores)
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
                "categoria": None,
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

        # Categoría tarifaria predominante (traducida de su código).
        categoria = None
        if "catetar" in d.columns and d["catetar"].notna().any():
            catetar_crudo = d["catetar"].dropna().mode().iloc[0]
            categoria = _traducir_categoria(catetar_crudo)
            logger.info(
                "[PRE_RECORD_FACTURACION] categoria: catetar_crudo=%r -> %r", catetar_crudo, categoria,
            )

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
            "categoria": categoria,
            "formaPredominante": forma_predominante,
            "totalMeses": int(len(d)),
            "totalPromediados": int((~d["esMedido"]).sum()),
            "mesesPromediados": meses_promediados,
            "rachaPromediados": racha_promediados,
        }
