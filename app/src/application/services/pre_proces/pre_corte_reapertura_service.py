import re
import time
import logging
from dataclasses import fields
from typing import get_args, get_type_hints

import pandas as pd

from app.src.core.model.corte_reapertura import CorteReapertura, RegistroCorteReapertura
from app.src.application.adapters.emapa_api import obtener_corte_reapertura
from app.src.application.services.pre_proces.df_utils import df_a_registros
from app.src.application.services.pre_proces.ventana_utils import calcular_ventana


logger = logging.getLogger("services.pre_corte_reapertura_service")

# Clasificación del evento a partir de codoperacion + tipooperacion.
CODOP_PRORROGA = "003"
TIPOOP_REAPERTURA = "002"

# Detecta menciones de reclamos previos en la observación.
PATRON_RECLAMO = re.compile(r"[Rr]eclamo\s+Nro\.?\s*(\d+)")

# Los "datos relevantes" son los atributos de RegistroCorteReapertura
# (única fuente de verdad).
COLUMNAS = [f.name for f in fields(RegistroCorteReapertura)]
_HINTS = get_type_hints(RegistroCorteReapertura)
CAMPOS_NUMERICOS = [n for n, t in _HINTS.items() if float in get_args(t) or t is float]


class PreCorteReaperturaService:
    """Preprocesa el histórico de cortes/reaperturas/prórrogas y filtra por la
    ventana de meses fijada por la tarjeta de lecturas. Devuelve la entidad
    CorteReapertura con los indicadores ya calculados para el análisis del
    medio probatorio.

    Nota: cada evento se ubica por su (`anio`, `mes`) del ciclo (que se toma
    como la fecha real del corte/reapertura/prórroga). `fechacorte` se
    conserva por trazabilidad pero no se usa para clasificar meses porque el
    origen la reporta con inconsistencias.
    """

    def preprocesar_corte_reapertura(
        self, codsuc: str, codcliente: str, meses: int = 12,
        fecha_ref: str | None = None,
    ) -> dict:
        t1 = time.time()
        # Ventana CALENDARIO calculada de antemano (independiente de qué medio se
        # analice primero; ver ventana_utils.py).
        ventana = calcular_ventana(fecha_ref, meses)

        json_raw = obtener_corte_reapertura(codsuc, codcliente)
        logger.info("[PRE_CORTE_REAPERTURA] Datos obtenidos de EMAPA en %.2f s", time.time() - t1)

        corte, df = self._construir_corte(json_raw, ventana)

        total = corte.totalCortes + corte.totalReaperturas + corte.totalProrrogas
        logger.info(
            "[PRE_CORTE_REAPERTURA] Preprocesamiento completo en %.2f s | eventos=%d | ventana=%d meses",
            time.time() - t1, total, len(ventana),
        )
        return {"corte": corte, "df": df}

    def _construir_corte(
        self, json_raw: dict, ventana: list[tuple[int, int]],
    ) -> tuple[CorteReapertura, pd.DataFrame]:
        registros = (json_raw or {}).get("data") or []
        if not registros:
            logger.warning("[PRE_CORTE_REAPERTURA] JSON sin registros en 'data'")
            return CorteReapertura(), pd.DataFrame(columns=COLUMNAS)

        df_raw = pd.DataFrame(registros)
        codcliente = str(df_raw["codcliente"].iloc[0]) if "codcliente" in df_raw.columns else None
        total_originales = len(df_raw)

        # 1. Tipar año/mes y filtrar por la ventana (inner join).
        df = df_raw.copy()
        df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
        df["mes"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int64")
        if ventana:
            ventana_df = pd.DataFrame(ventana, columns=["anio", "mes"])
            ventana_df["anio"] = ventana_df["anio"].astype("Int64")
            ventana_df["mes"] = ventana_df["mes"].astype("Int64")
            df = df.merge(ventana_df, on=["anio", "mes"], how="inner")
        logger.info("[PRE_CORTE_REAPERTURA] Eventos en la ventana: %d (de %d originales)", len(df), total_originales)

        # Si la ventana filtró todo, devolver entidad vacía con aviso.
        sin_registros_en_ventana = ventana and len(df) == 0 and total_originales > 0
        if sin_registros_en_ventana:
            logger.info(
                "[PRE_CORTE_REAPERTURA] Sin eventos de corte/reapertura en la ventana de %d meses "
                "(existían %d registros fuera de la ventana)",
                len(ventana), total_originales,
            )
            corte = CorteReapertura(
                codcliente=codcliente,
                sinRegistrosEnVentana=True,
                totalRegistrosOriginales=total_originales,
            )
            return corte, pd.DataFrame(columns=COLUMNAS)

        # 2. Limpieza: conservar solo columnas relevantes y tipar numéricos.
        df = df[[c for c in COLUMNAS if c in df.columns]].copy()
        for col in CAMPOS_NUMERICOS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Float64")
        # Orden cronológico (por fechareg como desempate dentro de un mes).
        orden = ["anio", "mes"] + (["fechareg"] if "fechareg" in df.columns else [])
        df = df.sort_values(orden).reset_index(drop=True)

        indicadores = self._calcular_indicadores(df)
        corte = CorteReapertura(
            codcliente=codcliente,
            totalRegistrosOriginales=total_originales,
            registros=df_a_registros(df),
            **indicadores,
        )
        return corte, df

    def _calcular_indicadores(self, df: pd.DataFrame) -> dict:
        """Clasifica cada evento y agrupa los hallazgos por mes (AAAA-MM)."""
        cortes_grp: dict[str, list[str]] = {}
        reap_grp: dict[str, list[str]] = {}
        prorr_grp: dict[str, list[str]] = {}
        reclamos_grp: dict[str, list[str]] = {}
        cortados: set[str] = set()
        total_cortes = total_reap = total_prorr = 0

        for r in df.to_dict("records"):
            if pd.isna(r.get("anio")) or pd.isna(r.get("mes")):
                continue
            anio, mes = int(r["anio"]), int(r["mes"])
            etiqueta = f"{anio}-{mes:02d}"
            codop = str(r.get("codoperacion") or "")
            tipoop = str(r.get("tipooperacion") or "")
            obs_raw = r.get("observacion")
            obs = str(obs_raw).strip() if pd.notna(obs_raw) else ""

            # --- Clasificación ---
            if codop == CODOP_PRORROGA:
                total_prorr += 1
                prorr_grp.setdefault(etiqueta, []).append(obs or "prórroga")
            elif tipoop == TIPOOP_REAPERTURA:
                total_reap += 1
                reap_grp.setdefault(etiqueta, []).append(obs or "reapertura por pago")
            else:
                total_cortes += 1
                partes = ["corte por deuda"]
                lu = r.get("lecturaultima")
                if pd.notna(lu):
                    partes.append(f"lectura {float(lu):g}")
                if obs:
                    partes.append(obs)
                cortes_grp.setdefault(etiqueta, []).append(", ".join(partes))
                cortados.add(etiqueta)

            # --- Reclamos previos citados en la observación ---
            if obs:
                for m in PATRON_RECLAMO.finditer(obs):
                    reclamos_grp.setdefault(etiqueta, []).append(f"reclamo N° {m.group(1)}")

        def _fmt(grupo: dict[str, list[str]]) -> list[str]:
            return [f"{k}: {', '.join(v)}" for k, v in sorted(grupo.items())]

        return {
            "totalCortes": total_cortes,
            "totalReaperturas": total_reap,
            "totalProrrogas": total_prorr,
            "cortes": _fmt(cortes_grp),
            "reaperturas": _fmt(reap_grp),
            "prorrogas": _fmt(prorr_grp),
            "mesesCortados": sorted(cortados),
            "reclamosPrevios": _fmt(reclamos_grp),
        }
