"""Etapa 2: confirmación humana del gold.

Aplica sobre los JSON borrador (generados por `extraer_gold.py`) los datos que
un humano confirmó leyendo cada PDF:

- codsede / codsuc = "001" (fijos de EMAPA San Martín)
- codcliente = número de suministro
- medio_id: se promueve `medio_sugerido` (todos verificados correctos); el punto
  `analisis_normativo` queda con medio_id=None (no es un medio: alimenta la
  conclusión / fundamentación normativa).
- hechos: datos estructurados que afirma la descripción real de cada medio
  (para comparar objetivamente contra los datos de EMAPA).
- conclusion_hechos: datos clave del razonamiento del veredicto (para comparar la
  conclusión más allá del binario FUNDADO/INFUNDADO).

Este archivo ES la fuente de la confirmación humana (auditable/versionable).
Se ejecuta sobre la carpeta gold/ y reescribe cada JSON con _revisado_por_humano=true.

Uso:
    python -m app.test.informes.confirmar_gold --gold-dir app/test/informes/gold
"""

from __future__ import annotations

import argparse
import glob
import json
import os

# hechos[suministro][n_punto] = dict de datos estructurados de ese punto.
HECHOS: dict[str, dict[int, dict]] = {
    "6073": {  # 0099-2023 INFUNDADO (fuga visible en inodoro)
        1: {"medidor_operativo": True, "lectura_m3": 608, "tipo_predio": "vivienda familiar", "habitantes": 3, "fuga_visible": True, "detalle_fuga": "inodoro con agua al ras del tubo de rebose"},
        2: {"inodoros": 2, "lavatorios": 2, "duchas": 2, "grifos": 1, "fugas": True, "detalle_fuga": "fuga en 01 inodoro"},
        3: {"categoria": "domestico"},
    },
    "6317": {  # 0123-2023 INFUNDADO (fuga no visible, no reparada)
        1: {"medidor_operativo": True, "lectura_m3": 241, "tipo_predio": "vivienda comercial", "habitantes": 3, "fuga_no_visible": True},
        2: {"inodoros": 2, "lavatorios": 1, "duchas": 1, "grifos": 3, "tanques": 1, "estado": "buen estado", "fugas": False},
        3: {"categoria": "comercial"},
    },
    "56": {  # 0289-2023 INFUNDADO (sin fuga)
        1: {"medidor_operativo": True, "lectura_m3": 1877, "tipo_predio": "vivienda familiar / alquiler 3 hab / local celulares"},
        2: {"inodoros": 4, "lavatorios": 2, "duchas": 4, "grifos": 3, "tanques": 1, "estado": "buen estado", "fugas": False},
        3: {"categoria": "comercial"},
    },
    "181": {  # 0295-2023 INFUNDADO (sin fuga)
        1: {"medidor_operativo": True, "lectura_m3": 1924, "tipo_predio": "vivienda familiar", "habitantes": 2},
        2: {"inodoros": 3, "lavatorios": 3, "duchas": 3, "grifos": 2, "tanques": 2, "estado": "buen estado", "fugas": False},
        3: {"categoria": "domestico"},
    },
    "7686": {  # 0307-2023 FUNDADO (fuga no visible reparada)
        1: {"medidor_operativo": True, "lectura_m3": 2052, "tipo_predio": "alquiler 11 habitaciones", "fuga_no_visible": True},
        2: {"inodoros": 6, "lavatorios": 6, "duchas": 6, "grifos": 2, "estado": "buen estado", "fugas": False},
        3: {"categoria": "comercial"},
    },
    "489": {  # 0316-2023 FUNDADO (fuga no visible reparada) -- SIN inspección interna en el real
        1: {"medidor_operativo": True, "lectura_m3": 1882, "tipo_predio": "vivienda familiar", "habitantes": 3, "fuga_no_visible": True},
        2: {"categoria": "domestico"},
    },
    "22112": {  # 0326-2023 INFUNDADO (sin fuga)
        1: {"medidor_operativo": True, "lectura_m3": 1394, "tipo_predio": "vivienda familiar", "habitantes": 6},
        2: {"inodoros": 2, "duchas": 1, "grifos": 1, "estado": "buen estado", "fugas": False},
        3: {"categoria": "domestico"},
    },
    "3699": {  # 0334-2023 INFUNDADO (sin fuga)
        1: {"medidor_operativo": True, "lectura_m3": 282, "tipo_predio": "vivienda familiar", "habitantes": 1},
        2: {"inodoros": 3, "lavatorios": 3, "duchas": 3, "grifos": 1, "tanques": 1, "estado": "buen estado", "fugas": False},
        3: {"categoria": "comercial"},
    },
    "134": {  # 3294-2023 INFUNDADO (fuga visible en inodoro)
        1: {"medidor_operativo": True, "lectura_m3": 1569, "tipo_predio": "vivienda familiar / local comercial (óptica)", "habitantes": 3, "fuga_visible": True, "detalle_fuga": "fuga de agua dentro del predio"},
        2: {"inodoros": 5, "lavatorios": 5, "duchas": 4, "grifos": 3, "tanques": 1, "fugas": True, "detalle_fuga": "01 inodoro con fuga"},
        3: {"categoria": "comercial"},
    },
    "7175": {  # 3430-2022 FUNDADO (fuga no visible reparada)
        1: {"medidor_operativo": True, "lectura_m3": 8186, "tipo_predio": "local de venta de refrigerios", "fuga_no_visible": True},
        2: {"inodoros": 4, "lavatorios": 4, "duchas": 2, "urinarios": 1, "grifos": 4, "tanques": 2, "estado": "buen estado", "fugas": False},
        3: {"categoria": "comercial"},
    },
}

# conclusion_hechos[suministro] = datos clave del razonamiento del veredicto.
# fuga: sin_fuga | no_visible_no_reparada | no_visible_reparada | visible_inodoro
# facturacion: diferencia_lecturas | promedio_historico
CONCLUSION: dict[str, dict] = {
    "6073":  {"meses_reclamados": ["noviembre 2022"], "fuga": "visible_inodoro", "facturacion": "diferencia_lecturas", "base_legal": "Art. 88.3"},
    "6317":  {"meses_reclamados": ["octubre", "noviembre"], "fuga": "no_visible_no_reparada", "facturacion": "diferencia_lecturas", "base_legal": "Art. 88.3"},
    "56":    {"meses_reclamados": ["noviembre"], "fuga": "sin_fuga", "facturacion": "diferencia_lecturas"},
    "181":   {"meses_reclamados": ["noviembre"], "fuga": "sin_fuga", "facturacion": "diferencia_lecturas"},
    "7686":  {"meses_reclamados": ["noviembre"], "fuga": "no_visible_reparada", "facturacion": "promedio_historico", "refacturacion_m3": 96, "base_legal": "Art. 88.3"},
    "489":   {"meses_reclamados": ["octubre", "noviembre"], "fuga": "no_visible_reparada", "facturacion": "promedio_historico", "refacturacion_m3": 20, "base_legal": "Art. 88.3"},
    "22112": {"meses_reclamados": ["noviembre"], "fuga": "sin_fuga", "facturacion": "diferencia_lecturas"},
    "3699":  {"meses_reclamados": ["noviembre"], "fuga": "sin_fuga", "facturacion": "diferencia_lecturas"},
    "134":   {"meses_reclamados": ["octubre 2022"], "fuga": "visible_inodoro", "facturacion": "diferencia_lecturas", "base_legal": "Art. 88.3"},
    "7175":  {"meses_reclamados": ["agosto", "septiembre"], "fuga": "no_visible_reparada", "facturacion": "promedio_historico", "refacturacion_m3": 58, "base_legal": "Art. 88.3"},
}


def confirmar(data: dict) -> dict:
    sum_ = data["suministro"]
    data["codsede"] = "001"
    data["codsuc"] = "001"
    data["codcliente"] = sum_
    hechos_informe = HECHOS.get(sum_, {})
    for p in data["puntos"]:
        if p["medio_sugerido"] == "analisis_normativo":
            p["medio_id"] = None
        else:
            p["medio_id"] = p["medio_sugerido"]
        p["hechos"] = hechos_informe.get(p["n"], {})
    data["conclusion_hechos"] = CONCLUSION.get(sum_, {})
    data["_revisado_por_humano"] = True
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-dir", default="app/test/informes/gold")
    args = ap.parse_args()

    faltan = []
    for f in sorted(glob.glob(os.path.join(args.gold_dir, "*.json"))):
        data = json.load(open(f, encoding="utf-8"))
        if data["suministro"] not in HECHOS:
            faltan.append(data["suministro"])
        data = confirmar(data)
        json.dump(data, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        medios = [p["medio_id"] for p in data["puntos"] if p["medio_id"]]
        print(f"  OK sum={data['suministro']:6} | veredicto={data['veredicto_real']:9} | medios={medios}")
    if faltan:
        print("FALTAN hechos para suministros:", faltan)


if __name__ == "__main__":
    main()
