import re
import time
import logging
from dataclasses import fields
from typing import get_args, get_type_hints

import pandas as pd

from app.src.core.model.targeta_lecturas import TargetaLecturas, LecturaMensual
from app.src.core.model.indicadores.targeta_lecturas_indicadores import INDICADORES_TARJETA_LECTURA
from app.src.application.adapters.emapa_api import obtener_tarjeta_lectura
from app.src.application.services.pre_proces.df_utils import df_a_registros

logger = logging.getLogger("services.pre_targeta_lecturas_service")

# Códigos "normales" del origen y factor de consumo atípico.
ESTADO_SERVICIO_ACTIVO = "001"
ESTADO_MEDIDOR_OK = "001"

# Estados de lectura que NO constituyen un problema (informativos o esperados),
# aunque su código sea distinto de "000". No se reportan como hallazgo.
#   000 LECTURA NORMAL
#   002 LECTURAS IGUALES
#   005 MEDIDOR NUEVO
#   010 CONSUMO MENOR AL PROMEDIO
ESTADOS_LECTURA_NO_PROBLEMA = {"000", "002", "005", "010"}

# Códigos de estadolectura que representan un problema de CONSUMO (van a
# errorConsumo). El resto de códigos con problema van a errorLecturas.
#   001 CONSUMO EXCESIVO
#   008 CONSUMO ATIPICO
#   011 CONSUMO DOBLE AL PROMEDIO
ESTADOS_LECTURA_CONSUMO = {"001", "008", "011"}

# Detección de "fuga no visible reparada": un mes con consumo elevado
# (> FACTOR_ELEVADO x promedio histórico, o marcado como consumo atípico) seguido
# de un mes posterior cuyo consumo RETORNA al promedio (<= FACTOR_NORMAL x
# promedio). Esa caída evidencia que la fuga fue reparada y sustenta refacturar
# los meses reclamados por el promedio histórico (Art. 88.3 SUNASS).
FACTOR_ELEVADO = 1.8
FACTOR_NORMAL = 1.3

COLUMNAS = [f.name for f in fields(LecturaMensual)]
_HINTS = get_type_hints(LecturaMensual)
CAMPOS_NUMERICOS = [n for n, t in _HINTS.items() if float in get_args(t) or t is float]

def parse_anio_mes(fecha_ref: str | None) -> tuple[int, int] | None:
    """Extrae (año, mes) de la fecha de recepción del reclamo (fecharec), que
    EMAPA entrega en formato ISO 'AAAA-MM-DD' (p.ej. '2022-12-07').
    Devuelve None si viene vacía o con un formato inesperado."""
    if not fecha_ref:
        return None
    m = re.match(r"\s*(\d{4})-(\d{2})", str(fecha_ref))
    return (int(m.group(1)), int(m.group(2))) if m else None




class PreTargetaLecturasService:
    
    def preprocesar_targeta_lecturas(
        self, codsuc: str, codcliente: str, meses: int = 12,
        fecha_ref: str | None = None,
    ) -> dict:
        t1 = time.time()
        json_raw = obtener_tarjeta_lectura(codsuc, codcliente)
        logger.info("[PRE_TARGETA_LECTURAS] Datos obtenidos de EMAPA en %.2f segundos", time.time() - t1)

        targeta, df = self._construir_targeta(json_raw, meses, fecha_ref)

        hallazgos = sum(len(getattr(targeta, g)) for g in
                        ("errorConsumo", "errorLecturas", "errorReinstalacion", "errorServicio"))
        logger.info(
            "[PRE_TARGETA_LECTURAS] Preprocesamiento completo en %.2f s | meses=%d | hallazgos=%d",
            time.time() - t1, len(df), hallazgos,
        )
        # Calcula la ventana a partir del DataFrame ya filtrado.
        ventana = [(int(a), int(m)) for a, m in zip(df["anio"], df["mes"])
                   if pd.notna(a) and pd.notna(m)]
        logger.info("[PRE_TARGETA_LECTURAS] Ventana calculada: %d meses", len(ventana))
        return {"targeta": targeta, "df": df, "ventana": ventana}

    def _construir_targeta(
        self, json_raw: dict, meses: int, fecha_ref: str | None = None,
    ) -> tuple[TargetaLecturas, pd.DataFrame]:
        registros = (json_raw or {}).get("data") or []
        if not registros:
            logger.warning("[PRE_TARGETA_LECTURAS] JSON sin registros en 'data'")
            return TargetaLecturas(), pd.DataFrame(columns=COLUMNAS)

        df_raw = pd.DataFrame(registros)

        def _primer(col: str) -> str | None:
            if col in df_raw.columns and df_raw[col].notna().any():
                return str(df_raw[col].dropna().iloc[0])
            return None

        win = df_raw.copy()
        win["anio"] = pd.to_numeric(win["anio"], errors="coerce").astype("Int64")
        win["mes"] = pd.to_numeric(win["mes"], errors="coerce").astype("Int64")

        # Ventana anclada a la FECHA DE RECEPCIÓN del reclamo: se toman los últimos
        # `meses` registros hasta el mes de recepción (no los más recientes de hoy).
        # Esto es clave para reclamos históricos: si no se ancla, un reclamo de 2022
        # se analizaría con lecturas actuales (2025/2026). Si la fecha no se puede
        # interpretar, se cae al comportamiento previo (últimos `meses`).
        ref = parse_anio_mes(fecha_ref)
        if ref is not None:
            ra, rm = ref
            win = win[(win["anio"] < ra) | ((win["anio"] == ra) & (win["mes"] <= rm))]
            logger.info("[PRE_TARGETA_LECTURAS] Ventana anclada a recepción %02d/%d", rm, ra)
        elif fecha_ref:
            logger.warning("[PRE_TARGETA_LECTURAS] fecha_ref no interpretable (%r); "
                           "uso los últimos %d meses", fecha_ref, meses)
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



        indicadores = self._calcular_indicadores(df)
        targeta = TargetaLecturas(
            codcliente=_primer("codcliente"),
            nomtar=_primer("nomtar"),
            destipoactividad=_primer("destipoactividad"),
            tipopromedio=tipopromedio,
            registros=df_a_registros(df),
            **indicadores,
        )
        return targeta, df

    def _calcular_indicadores(self, df: pd.DataFrame) -> dict:
        """Recorre la ventana y agrupa los hallazgos por problema.

        Cada grupo mapea el *concepto* del problema (p.ej. "consumo atípico")
        a la lista de fechas (MM/AAAA) en que se detectó. Así un mismo problema
        aparece una sola vez con todas sus fechas, en lugar de repetirse por mes.
        """
        registros = df.to_dict("records")
        # concepto -> lista de fechas MM/AAAA en que ocurrió
        consumo_grp: dict[str, list[str]] = {}
        lectura_grp: dict[str, list[str]] = {}
        reinst_grp: dict[str, list[str]] = {}
        servicio_grp: dict[str, list[str]] = {}
        obs_grp: dict[str, list[str]] = {}

        def _add(grupo: dict[str, list[str]], concepto: str, fecha: str) -> None:
            fechas = grupo.setdefault(concepto, [])
            if fecha not in fechas:
                fechas.append(fecha)

        for i, r in enumerate(registros):
            if pd.isna(r.get("anio")) or pd.isna(r.get("mes")):
                continue
            anio, mes = int(r["anio"]), int(r["mes"])
            fecha = f"{mes:02d}/{anio}"
            prev = registros[i - 1] if i > 0 else None

            # --- Errores de lectura / consumo ---------------------------------
            # Nos apoyamos únicamente en el código estadolectura del origen; los
            # códigos de consumo van a errorConsumo y el resto a errorLecturas.
            estado_lec = str(r["estadolectura"]) if pd.notna(r.get("estadolectura")) else None
            es_problema_lec = bool(estado_lec) and estado_lec not in ESTADOS_LECTURA_NO_PROBLEMA
            if es_problema_lec:
                detalle = INDICADORES_TARJETA_LECTURA["estadolectura"].get(estado_lec, f"cód {estado_lec}")
                grupo = consumo_grp if estado_lec in ESTADOS_LECTURA_CONSUMO else lectura_grp
                _add(grupo, detalle.capitalize(), fecha)

            # Error de fecha: la lectura no pertenece al periodo facturado.
            # No está representado en estadolectura, por eso se evalúa aparte.
            fecha_lec = pd.to_datetime(r.get("fechalecturault"), errors="coerce")
            if pd.notna(fecha_lec) and (fecha_lec.year != anio or fecha_lec.month != mes):
                _add(lectura_grp, "error de fecha (lectura no pertenece al periodo)", fecha)

            # --- Errores por reinstalación ------------------------------------
            # Cambio de medidor coincidente con un consumo atípico del origen.
            es_atipico = estado_lec in ESTADOS_LECTURA_CONSUMO
            if prev is not None:
                nromed, nromed_prev = r.get("nromed"), prev.get("nromed")
                if nromed and nromed_prev and str(nromed) != str(nromed_prev) and es_atipico:
                    _add(reinst_grp, "cambio de medidor con consumo atípico", fecha)

            # --- Errores de servicio / medidor --------------------------------
            estado_serv = str(r["estadoservicio"]) if pd.notna(r.get("estadoservicio")) else None
            if estado_serv and estado_serv != ESTADO_SERVICIO_ACTIVO:
                # El texto oficial ya menciona "SERVICIO", no anteponemos prefijo.
                detalle = INDICADORES_TARJETA_LECTURA["estadoservicio"].get(estado_serv, f"cód {estado_serv}")
                _add(servicio_grp, detalle, fecha)
            estado_med = str(r["estadomed"]) if pd.notna(r.get("estadomed")) else None
            if estado_med and estado_med != ESTADO_MEDIDOR_OK:
                # Prefijo "medidor:" para distinguirlo del hallazgo de servicio.
                detalle = INDICADORES_TARJETA_LECTURA["estadomed"].get(estado_med, f"cód {estado_med}")
                _add(servicio_grp, f"medidor: {detalle}", fecha)

            # --- Observaciones de lectura -------------------------------------
            obs = r.get("obslectura")
            if obs and str(obs).strip():
                _add(obs_grp, str(obs).strip(), fecha)

        def _unir_fechas(fechas: list[str]) -> str:
            """['10/2025', '02/2026'] -> '10/2025 y 02/2026'."""
            if len(fechas) == 1:
                return fechas[0]
            return f"{', '.join(fechas[:-1])} y {fechas[-1]}"

        def _fmt(grupo: dict[str, list[str]]) -> list[str]:
            return [
                f"{concepto}: detectado en {_unir_fechas(fechas)}"
                for concepto, fechas in grupo.items()
            ]

        return {
            "errorConsumo": _fmt(consumo_grp),
            "errorLecturas": _fmt(lectura_grp),
            "errorReinstalacion": _fmt(reinst_grp),
            "errorServicio": _fmt(servicio_grp),
            "fugaReparada": self._detectar_fuga_reparada(df),
            "obslectura": _fmt(obs_grp),
        }

    def _detectar_fuga_reparada(self, df: pd.DataFrame) -> list[str]:
        """Detecta el patrón de fuga no visible reparada: uno o más meses con
        consumo elevado seguidos de un mes posterior cuyo consumo retorna al
        promedio histórico. Devuelve a lo sumo un hallazgo con las cifras.

        Se apoya en `consumo` y `lecturapromedio` de cada mes (más el código de
        consumo atípico del origen). Requiere la serie en orden cronológico."""
        regs = []
        for r in df.to_dict("records"):
            prom = r.get("lecturapromedio")
            cons = r.get("consumo")
            if (pd.notna(prom) and float(prom) > 0 and pd.notna(cons)
                    and pd.notna(r.get("anio")) and pd.notna(r.get("mes"))):
                regs.append(r)
        if len(regs) < 2:
            return []

        def _elevado(r) -> bool:
            prom, cons = float(r["lecturapromedio"]), float(r["consumo"])
            cod = str(r["estadolectura"]) if pd.notna(r.get("estadolectura")) else None
            return cons > FACTOR_ELEVADO * prom or cod in ESTADOS_LECTURA_CONSUMO

        def _normal(r) -> bool:
            return float(r["consumo"]) <= FACTOR_NORMAL * float(r["lecturapromedio"])

        idx_elevados = [i for i, r in enumerate(regs) if _elevado(r)]
        if not idx_elevados:
            return []
        # ¿Algún mes POSTERIOR al último elevado retornó al promedio?
        posteriores_normales = [r for r in regs[idx_elevados[-1] + 1:] if _normal(r)]
        if not posteriores_normales:
            return []

        pico = max((regs[i] for i in idx_elevados), key=lambda r: float(r["consumo"]))
        post = posteriores_normales[0]

        def _fecha(r) -> str:
            return f"{int(r['mes']):02d}/{int(r['anio'])}"

        msg = (
            f"Consumo elevado de {float(pico['consumo']):.0f} m³ en {_fecha(pico)} "
            f"que retorna a {float(post['consumo']):.0f} m³ en {_fecha(post)} "
            f"(promedio histórico {float(post['lecturapromedio']):.0f} m³), lo que "
            f"evidencia una fuga no visible ya reparada."
        )
        logger.info("[PRE_TARGETA_LECTURAS] Fuga reparada detectada: %s", msg)
        return [msg]
