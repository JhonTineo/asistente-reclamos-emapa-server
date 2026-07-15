import time
import logging
from dataclasses import fields
from typing import get_args, get_type_hints

import pandas as pd

from app.src.core.model.targeta_lecturas import TargetaLecturas, LecturaMensual
from app.src.core.model.indicadores.targeta_lecturas_indicadores import INDICADORES_TARJETA_LECTURA
from app.src.core.service.tools.emapa_api import obtener_tarjeta_lectura

logger = logging.getLogger("services.pre_targeta_lecturas_service")

# Códigos "normales" del origen y factor de consumo atípico.
ESTADO_LECTURA_NORMAL = "000"
ESTADO_SERVICIO_ACTIVO = "001"
ESTADO_MEDIDOR_OK = "001"
FACTOR_ATIPICO = 2  # consumo atípico: mayor al doble del promedio del mes

COLUMNAS = [f.name for f in fields(LecturaMensual)]
_HINTS = get_type_hints(LecturaMensual)
CAMPOS_NUMERICOS = [n for n, t in _HINTS.items() if float in get_args(t) or t is float]

# Ventana de análisis: lista de (año, mes) que otros medios probatorios
# (corte/reapertura, facturación, etc.) consultan para mantenerse alineados
# al mismo periodo. Solución temporal; sustituir por un contexto explícito.
MESES_VENTANA: list[tuple[int, int]] = []


class PreTargetaLecturasService:
    
    def preprocesar_targeta_lecturas(self, codsuc: str, codcliente: str, meses: int = 12) -> dict:
        t1 = time.time()
        json_raw = obtener_tarjeta_lectura(codsuc, codcliente)
        logger.info("[PRE_TARGETA_LECTURAS] Datos obtenidos de EMAPA en %.2f segundos", time.time() - t1)

        targeta, df = self._construir_targeta(json_raw, meses)

        hallazgos = sum(len(getattr(targeta, g)) for g in
                        ("errorConsumo", "errorLecturas", "errorReinstalacion", "errorServicio"))
        logger.info(
            "[PRE_TARGETA_LECTURAS] Preprocesamiento completo en %.2f s | meses=%d | hallazgos=%d",
            time.time() - t1, len(df), hallazgos,
        )
        return {"targeta": targeta, "df": df}

    def _construir_targeta(self, json_raw: dict, meses: int) -> tuple[TargetaLecturas, pd.DataFrame]:
        registros = (json_raw or {}).get("data") or []
        if not registros:
            logger.warning("[PRE_TARGETA_LECTURAS] JSON sin registros en 'data'")
            return TargetaLecturas(), pd.DataFrame(columns=COLUMNAS)

        df_raw = pd.DataFrame(registros)

        def _primer(col: str) -> str | None:
            if col in df_raw.columns and df_raw[col].notna().any():
                return str(df_raw[col].dropna().iloc[0])
            return None

        # Ventana: últimos `meses` registros ordenados por (año, mes).
        win = df_raw.copy()
        win["anio"] = pd.to_numeric(win["anio"], errors="coerce").astype("Int64")
        win["mes"] = pd.to_numeric(win["mes"], errors="coerce").astype("Int64")
        win = win.sort_values(["anio", "mes"], ascending=False).head(meses)

        # tipopromedio (escalar): tipo de promedio predominante en la ventana.
        tipopromedio = None
        if "destipopromedio" in win.columns:
            modo = win["destipopromedio"].mode()
            tipopromedio = modo.iloc[0] if not modo.empty else None

        # Serie limpia (solo columnas relevantes) en orden cronológico.
        df = win[[c for c in COLUMNAS if c in win.columns]].copy()
        for col in CAMPOS_NUMERICOS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Float64")
        df = df.sort_values(["anio", "mes"]).reset_index(drop=True)

        # Publica la ventana para que otros medios probatorios se alineen.
        global MESES_VENTANA
        MESES_VENTANA = [(int(a), int(m)) for a, m in zip(df["anio"], df["mes"])
                         if pd.notna(a) and pd.notna(m)]
        logger.info("[PRE_TARGETA_LECTURAS] Ventana publicada: %d meses", len(MESES_VENTANA))

        indicadores = self._calcular_indicadores(df)
        targeta = TargetaLecturas(
            codcliente=_primer("codcliente"),
            nomtar=_primer("nomtar"),
            destipoactividad=_primer("destipoactividad"),
            tipopromedio=tipopromedio,
            **indicadores,
        )
        return targeta, df

    def _calcular_indicadores(self, df: pd.DataFrame) -> dict:
        """Recorre la ventana y agrupa los hallazgos por mes (AAAA-MM)."""
        registros = df.to_dict("records")
        consumo_grp: dict[str, list[str]] = {}
        lectura_grp: dict[str, list[str]] = {}
        reinst_grp: dict[str, list[str]] = {}
        servicio_grp: dict[str, list[str]] = {}
        obs_grp: dict[str, list[str]] = {}

        for i, r in enumerate(registros):
            if pd.isna(r.get("anio")) or pd.isna(r.get("mes")):
                continue
            anio, mes = int(r["anio"]), int(r["mes"])
            etiqueta = f"{anio}-{mes:02d}"
            prev = registros[i - 1] if i > 0 else None
            consumo = r.get("consumo")
            la, lu = r.get("lecturaanterior"), r.get("lecturaultima")
            prom = r.get("lecturapromedio")

            # --- Errores de lectura -------------------------------------------
            estado_lec = str(r["estadolectura"]) if pd.notna(r.get("estadolectura")) else None
            if estado_lec and estado_lec != ESTADO_LECTURA_NORMAL:
                detalle = INDICADORES_TARJETA_LECTURA["estadolectura"].get(estado_lec, f"cód {estado_lec}")
                lectura_grp.setdefault(etiqueta, []).append(f"sin lectura normal ({detalle})")
            if pd.notna(la) and pd.notna(lu) and float(lu) < float(la):
                lectura_grp.setdefault(etiqueta, []).append(
                    f"consumo negativo (última {float(lu):g} < anterior {float(la):g})"
                )
            fecha = pd.to_datetime(r.get("fechalecturault"), errors="coerce")
            if pd.notna(fecha) and (fecha.year != anio or fecha.month != mes):
                lectura_grp.setdefault(etiqueta, []).append(
                    f"error de fecha (lectura {fecha.date()} no pertenece a {etiqueta})"
                )

            # --- Errores de consumo -------------------------------------------
            es_atipico = (pd.notna(consumo) and pd.notna(prom) and float(prom) > 0
                          and float(consumo) > FACTOR_ATIPICO * float(prom))
            if es_atipico:
                consumo_grp.setdefault(etiqueta, []).append(
                    f"consumo atípico ({float(consumo):g} m³ > 2×promedio {float(prom):g})"
                )
            if (prev is not None and pd.notna(consumo) and pd.notna(prev.get("consumo"))
                    and float(consumo) > 0 and float(consumo) == float(prev["consumo"])):
                consumo_grp.setdefault(etiqueta, []).append(
                    f"doble consumo ({float(consumo):g} m³ igual al mes anterior)"
                )

            # --- Errores por reinstalación ------------------------------------
            if prev is not None:
                nromed, nromed_prev = r.get("nromed"), prev.get("nromed")
                if nromed and nromed_prev and str(nromed) != str(nromed_prev) and es_atipico:
                    reinst_grp.setdefault(etiqueta, []).append(
                        f"cambio de medidor ({nromed_prev}→{nromed}) con consumo atípico "
                        f"({float(consumo):g} m³)"
                    )

            # --- Errores de servicio / medidor --------------------------------
            estado_serv = str(r["estadoservicio"]) if pd.notna(r.get("estadoservicio")) else None
            if estado_serv and estado_serv != ESTADO_SERVICIO_ACTIVO:
                # El texto oficial ya menciona "SERVICIO", no anteponemos prefijo.
                detalle = INDICADORES_TARJETA_LECTURA["estadoservicio"].get(estado_serv, f"cód {estado_serv}")
                servicio_grp.setdefault(etiqueta, []).append(detalle)
            estado_med = str(r["estadomed"]) if pd.notna(r.get("estadomed")) else None
            if estado_med and estado_med != ESTADO_MEDIDOR_OK:
                # Prefijo "medidor:" para distinguirlo del hallazgo de servicio.
                detalle = INDICADORES_TARJETA_LECTURA["estadomed"].get(estado_med, f"cód {estado_med}")
                servicio_grp.setdefault(etiqueta, []).append(f"medidor: {detalle}")

            # --- Observaciones de lectura -------------------------------------
            obs = r.get("obslectura")
            if obs and str(obs).strip():
                obs_grp.setdefault(etiqueta, []).append(str(obs).strip())

        def _fmt(grupo: dict[str, list[str]]) -> list[str]:
            return [f"{etiqueta}: {', '.join(items)}" for etiqueta, items in grupo.items()]

        return {
            "errorConsumo": _fmt(consumo_grp),
            "errorLecturas": _fmt(lectura_grp),
            "errorReinstalacion": _fmt(reinst_grp),
            "errorServicio": _fmt(servicio_grp),
            "obslectura": _fmt(obs_grp),
        }
