"""Etapa 3a: regenera el informe de atención con la herramienta (API en vivo).

Por cada gold confirmado, reproduce el flujo real de la herramienta llamando a
los endpoints en el mismo orden que el frontend:

    GET  /reclamos/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}   (guarda token+motivo+clasificación en el server)
    POST /investigacion/objetivos
    POST /investigacion/tarjeta-lectura      (primero: fija la ventana de meses)
    POST /investigacion/record-facturacion
    POST /investigacion/corte-reapertura
    POST /investigacion/saldo-detalle
    POST /investigacion/inspeccion-externa
    POST /investigacion/inspeccion-interna
    POST /investigacion/conclusion

Guarda TODAS las salidas intermedias (objetivos, datos EMAPA, resumen y
problemas por medio, conclusión y veredicto) en salidas/<codreclamo>_runN.json.
Repite --runs veces por caso para medir estabilidad del veredicto.

El veredicto NO viene como campo en la respuesta de /conclusion: se extrae del
texto del informe (misma regla 'se declara FUNDADO/INFUNDADO' que en el real).

Uso:
    export EMAPA_TOKEN="Bearer eyJ..."   # o --token
    python -m app.test.informes.correr_herramienta \
        --base-url https://w5vo8nfdqsfk495lkv1n78mr.187.127.35.217.sslip.io \
        --gold-dir app/test/informes/gold \
        --out-dir  app/test/informes/salidas \
        --runs 2
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import time
from pathlib import Path

import requests

# Orden de análisis. tarjeta_lectura va primero porque fija la ventana de meses
# que los demás medios reutilizan (ver investigacion.py).
ORDEN_MEDIOS = [
    ("tarjeta-lectura", "tarjeta_lectura"),
    ("record-facturacion", "record_facturacion"),
    ("corte-reapertura", "corte_reapertura"),
    ("saldo-detalle", "saldo_detalle"),
    ("inspeccion-externa", "inspeccion_externa"),
    ("inspeccion-interna", "inspeccion_interna"),
]

_RE_VEREDICTO = re.compile(r"se\s+declara\s+\**\s*(fundado|infundado)", re.IGNORECASE)


def extraer_veredicto(texto: str | None) -> str | None:
    if not texto:
        return None
    m = _RE_VEREDICTO.search(texto)
    return m.group(1).upper() if m else None


def _campo_reclamo(datos: dict | None, campo: str) -> str:
    """Lee un campo del JSON del reclamo (data puede ser dict o lista)."""
    data = datos.get("data") if isinstance(datos, dict) else None
    if isinstance(data, dict):
        return str(data.get(campo) or "").strip()
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get(campo) or "").strip()
    return ""


class HerramientaClient:
    def __init__(self, base_url: str, token: str | None, modelo: str | None, timeout: int):
        self.base = base_url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout
        self.s = requests.Session()
        if token:
            if not token.lower().startswith("bearer "):
                token = "Bearer " + token
            self.s.headers["Authorization"] = token

    def buscar_reclamo(self, codsede, codsuc, codreclamo, codcliente) -> dict:
        url = f"{self.base}/reclamos/reclamo/{codsede}/{codsuc}/{codreclamo}/{codcliente}"
        r = self.s.get(url, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def objetivos(self, codreclamo) -> dict:
        r = self.s.post(f"{self.base}/investigacion/objetivos",
                        json={"codreclamo": codreclamo, "modelo": self.modelo},
                        timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def medio(self, ruta, codsuc, codreclamo, codcliente, clasificacion, meses) -> dict:
        r = self.s.post(f"{self.base}/investigacion/{ruta}", json={
            "codsuc": codsuc, "codreclamo": codreclamo, "codcliente": codcliente,
            "clasificacion": clasificacion, "meses": meses, "modelo": self.modelo,
        }, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def conclusion(self, codreclamo, clasificacion) -> dict:
        r = self.s.post(f"{self.base}/investigacion/conclusion", json={
            "codreclamo": codreclamo, "clasificacion": clasificacion, "modelo": self.modelo,
        }, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def correr_caso(cli: HerramientaClient, gold: dict, meses: int) -> dict:
    codsede, codsuc = gold["codsede"], gold["codsuc"]
    codreclamo, codcliente = gold["codreclamo"], gold["codcliente"]
    errores: list[str] = []

    # 1. Buscar reclamo (guarda token/motivo/clasificación en el server).
    busqueda = cli.buscar_reclamo(codsede, codsuc, codreclamo, codcliente)
    clasificacion = _campo_reclamo(busqueda.get("datos"), "desCodReclamo")
    motivo = _campo_reclamo(busqueda.get("datos"), "motivo")

    # 2. Objetivos.
    try:
        objetivos = cli.objetivos(codreclamo)
    except Exception as e:  # noqa: BLE001
        objetivos = {"error": str(e)}
        errores.append(f"objetivos: {e}")

    # 3. Medios (en orden; tarjeta primero).
    medios: dict[str, dict] = {}
    for ruta, medio_id in ORDEN_MEDIOS:
        try:
            medios[medio_id] = cli.medio(ruta, codsuc, codreclamo, codcliente, clasificacion, meses)
        except Exception as e:  # noqa: BLE001
            medios[medio_id] = {"error": str(e)}
            errores.append(f"{medio_id}: {e}")

    # 4. Conclusión.
    try:
        concl = cli.conclusion(codreclamo, clasificacion)
    except Exception as e:  # noqa: BLE001
        concl = {"error": str(e)}
        errores.append(f"conclusion: {e}")

    veredicto = extraer_veredicto(concl.get("informe"))

    return {
        "codreclamo": codreclamo,
        "suministro": gold["suministro"],
        "clasificacion_emapa": clasificacion,
        "motivo_emapa": motivo,
        "veredicto_generado": veredicto,
        "objetivos": objetivos,
        "medios": medios,
        "conclusion": concl,
        "errores": errores,
    }


def main() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows: evita cp1252 en consola
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--gold-dir", default="app/test/informes/gold")
    ap.add_argument("--out-dir", default="app/test/informes/salidas")
    ap.add_argument("--token", default=os.environ.get("EMAPA_TOKEN"))
    ap.add_argument("--modelo", default=None, help="Modelo LLM (opcional; usa el default del server)")
    ap.add_argument("--meses", type=int, default=12)
    ap.add_argument("--runs", type=int, default=1, help="Corridas por caso (estabilidad)")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--solo", default=None, help="Filtra por suministro (coma-separado)")
    args = ap.parse_args()

    if not args.token:
        raise SystemExit("Falta el token EMAPA: usa --token o la variable EMAPA_TOKEN.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cli = HerramientaClient(args.base_url, args.token, args.modelo, args.timeout)

    golds = []
    for f in sorted(glob.glob(os.path.join(args.gold_dir, "*.json"))):
        g = json.load(open(f, encoding="utf-8"))
        if not g.get("_revisado_por_humano"):
            print(f"  SALTA {os.path.basename(f)} (no revisado por humano)")
            continue
        if args.solo and g["suministro"] not in args.solo.split(","):
            continue
        golds.append(g)

    print(f"Casos a correr: {len(golds)} | runs c/u: {args.runs}")
    for g in golds:
        for run in range(1, args.runs + 1):
            t0 = time.perf_counter()
            try:
                res = correr_caso(cli, g, args.meses)
            except Exception as e:  # noqa: BLE001
                res = {"codreclamo": g["codreclamo"], "suministro": g["suministro"],
                       "error_fatal": str(e)}
            res["_run"] = run
            res["_tiempo_s"] = round(time.perf_counter() - t0, 1)
            out = out_dir / f"{g['codreclamo']}_run{run}.json"
            out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            vg = res.get("veredicto_generado")
            errs = len(res.get("errores", [])) if "errores" in res else "FATAL"
            print(f"  sum={g['suministro']:6} run={run} | real={g['veredicto_real']:9} "
                  f"gen={str(vg):9} | errores={errs} | {res['_tiempo_s']}s")


if __name__ == "__main__":
    main()
