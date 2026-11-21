"""Evaluación y calibración de la búsqueda vectorial de normativa.

Corre los casos de `casos.json` contra Qdrant (las mismas colecciones, el mismo
modelo de embeddings y la misma construcción de query que la fundamentación) y
reporta:

  1. Por caso: en qué posición aparece el primer artículo esperado y su score.
  2. Recall@k y MRR: ¿el artículo correcto llega al top k?
  3. Distribución de scores: relevantes vs. no relevantes vs. consultas basura.
  4. Barrido de umbral absoluto y relativo, para elegir UMBRAL_SCORE con datos.

Uso (desde la raíz del repo, con Qdrant y Ollama levantados):

    $env:QDRANT_URL="http://127.0.0.1:6333"; $env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
    .venv\\Scripts\\python.exe herramientas\\calibracion_rag\\evaluar.py

Opcional: --json salida.json para guardar los resultados crudos.
"""

import argparse
import time
import json
import os
import statistics
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(RAIZ, ".env"))

from app.src.application.services.rag.retriever import Retriever  # noqa: E402
from app.src.application.usecase.pasos.fundamentacion import (  # noqa: E402
    COLECCIONES, TOP_K, UMBRAL_SCORE, PasoFundamentacion, premisa_no_cumplida,
)
from app.src.core.model.informe_atencion import ProblemaNormado  # noqa: E402
from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter  # noqa: E402

PREFIJO = {"sunass_reglamento": "C", "sunass_reclamos": "R"}
PROFUNDIDAD = 20


def etiqueta(r: dict) -> str:
    p = r["payload"]
    base = f"{PREFIJO.get(r['coleccion'], '?')}{p.get('article')}"
    return f"{base} {p['numeral']}" if p.get("numeral") else base


def es_esperado(r: dict, esperados: list[str]) -> bool:
    p = r["payload"]
    pref = PREFIJO.get(r["coleccion"], "?")
    art = f"{pref}{p.get('article')}"
    num = f"{pref}{p.get('numeral')}" if p.get("numeral") else None
    return any(e == art or (num and e == num) for e in esperados)


def pct(valores, q):
    if not valores:
        return float("nan")
    v = sorted(valores)
    return v[min(len(v) - 1, int(q * len(v)))]


def evaluar_punta_a_punta(data: dict, metodo: str, proveedor: str | None, salida: str | None) -> None:
    """Lo que de verdad llega al párrafo: búsqueda de producción
    (PasoFundamentacion.buscar_articulos, con TOP_K y umbral en el vectorial)
    + marcar_aplica (LLM). Un caso ACIERTA si al menos un artículo esperado
    queda con aplica=true; RUIDO = artículos con aplica=true que no son esperados."""
    from types import SimpleNamespace
    from app.src.infrastructure.api_rest.deps import get_llm_router
    router = get_llm_router(SimpleNamespace(headers={"X-LLM-Provider": proveedor} if proveedor else {}))
    paso = PasoFundamentacion(qdrant=QdrantAdapter() if metodo == "vectorial" else None,
                              llm_router=router, metodo=metodo)
    print(f"PUNTA A PUNTA | método={metodo} | proveedor={proveedor or 'auto'}\n")
    filas = []
    for caso in data["casos"]:
        problema = ProblemaNormado(tipo=caso["tipo"], detalle=caso["detalle"], valor=caso.get("valor"))
        situacion, motivo = caso.get("situacion"), caso.get("motivo", "")
        t0 = time.perf_counter()
        raw = paso.buscar_articulos(problema, motivo, situacion)
        t_busqueda = time.perf_counter() - t0
        payload = paso.marcar_aplica(problema, raw, "A1. CONSUMO MEDIDO", motivo, situacion)
        t_total = time.perf_counter() - t0
        aplican = [(etiqueta(r), es_esperado(r, caso["esperados"]))
                   for r, a in zip(raw, payload) if a.get("aplica")]
        filas.append({"id": caso["id"], "candidatos": len(raw), "aplican": aplican,
                      "acierta": any(ok for _, ok in aplican),
                      "ruido": sum(1 for _, ok in aplican if not ok),
                      "t_busqueda": t_busqueda, "t_total": t_total})
        marcas = "  ".join(f"{'*' if ok else '-'}{e}" for e, ok in aplican) or "(ninguno)"
        print(f"{caso['id']:<30} {'OK ' if filas[-1]['acierta'] else 'MAL'} cand={len(raw):<3} "
              f"t={t_total:4.1f}s | {marcas}")
    n = len(filas)
    print("\n" + "=" * 100)
    print(f"   aciertos  = {sum(f['acierta'] for f in filas)}/{n} = {sum(f['acierta'] for f in filas) / n:.0%}")
    print(f"   ruido     = {sum(f['ruido'] for f in filas)} artículos marcados que no son esperados "
          f"({sum(f['ruido'] for f in filas) / n:.2f} por caso)")
    print(f"   candidatos: mediana {statistics.median(f['candidatos'] for f in filas):.0f}")
    print(f"   tiempo búsqueda: mediana {statistics.median(f['t_busqueda'] for f in filas):.2f}s | "
          f"búsqueda+aplica: mediana {statistics.median(f['t_total'] for f in filas):.2f}s, "
          f"máx {max(f['t_total'] for f in filas):.2f}s")
    print(f"   fallan: {', '.join(f['id'] for f in filas if not f['acierta']) or '(ninguno)'}")
    if salida:
        with open(salida, "w", encoding="utf-8") as fh:
            json.dump(filas, fh, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--casos", default=os.path.join(os.path.dirname(__file__), "casos.json"))
    ap.add_argument("--json", help="guardar resultados crudos")
    ap.add_argument("--metodo", choices=("vectorial", "indice"), default="vectorial",
                    help="indice: el LLM elige artículos desde el índice de títulos + BM25 "
                         "sobre la base normativa (necesita API keys de LLM en .env)")
    ap.add_argument("--proveedor", help="con --metodo indice: proveedor de LLM a usar primero "
                                        "(cerebras, groq, gemini, ...); por defecto el orden automático")
    ap.add_argument("--aplica", action="store_true",
                    help="punta a punta como producción: búsqueda (con su TOP_K/umbral) + "
                         "marcar_aplica con el LLM; mide acierto, ruido y tiempo")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    with open(args.casos, encoding="utf-8") as f:
        data = json.load(f)

    if args.aplica:
        evaluar_punta_a_punta(data, args.metodo, args.proveedor, args.json)
        return

    paso = None
    if args.metodo == "indice":
        from types import SimpleNamespace
        from app.src.infrastructure.api_rest.deps import get_llm_router
        router = get_llm_router(SimpleNamespace(
            headers={"X-LLM-Provider": args.proveedor} if args.proveedor else {}))
        paso = PasoFundamentacion(qdrant=None, llm_router=router, metodo="indice")
        print(f"Método: índice ({len(paso.catalogo.unidades)} unidades, índice ≈"
              f"{len(paso.catalogo.indice()) // 4} tokens) + BM25 | TOP_K={TOP_K}\n")
    else:
        retriever = Retriever(QdrantAdapter())
        print(f"Modelo: {retriever.embedder.model_name} | colecciones: {', '.join(COLECCIONES)} "
              f"| TOP_K={TOP_K} | UMBRAL_SCORE actual={UMBRAL_SCORE}\n")
    tiempos = []

    resultados = []
    for caso in data["casos"]:
        problema = ProblemaNormado(tipo=caso["tipo"], detalle=caso["detalle"], valor=caso.get("valor"))
        situacion = caso.get("situacion")
        query = PasoFundamentacion.construir_query(problema, caso.get("motivo", ""), situacion)
        t0 = time.perf_counter()
        if paso is not None:
            res = paso.buscar_articulos(problema, caso.get("motivo", ""), situacion)
        else:
            res = retriever.retrieve(query, top_k=PROFUNDIDAD, collections=COLECCIONES)
        tiempos.append(time.perf_counter() - t0)
        # Igual que producción: marcar_aplica descarta los artículos cuya
        # premisa no se da en el caso (sin medidor, régimen atípico, etc.).
        res = [r for r in res if not premisa_no_cumplida(
            {"article": r["payload"].get("article"), "numeral": r["payload"].get("numeral"),
             "texto": r["payload"].get("text")}, situacion)]
        marcados = [
            {"etiqueta": etiqueta(r), "score": r["score"], "ok": es_esperado(r, caso["esperados"])}
            for r in res
        ]
        primero = next((i + 1 for i, m in enumerate(marcados) if m["ok"]), None)
        resultados.append({"caso": caso, "query": query, "res": marcados, "rank": primero})

    basura = []
    for q in (data.get("basura", []) if paso is None else []):
        res = retriever.retrieve(q, top_k=TOP_K, collections=COLECCIONES)
        basura.append({"query": q, "res": [{"etiqueta": etiqueta(r), "score": r["score"]} for r in res]})

    # ------------------------------------------------------------- 1) por caso
    print("=" * 100)
    print("1) POR CASO  (rank = posición del primer esperado; * = esperado)")
    print("=" * 100)
    for r in resultados:
        c = r["caso"]
        top = "  ".join(
            f"{'*' if m['ok'] else ' '}{m['etiqueta']}({m['score']:.3f})" for m in r["res"][:TOP_K]
        )
        rank = r["rank"] if r["rank"] else f">{PROFUNDIDAD}"
        print(f"{c['id']:<30} rank={str(rank):<4} | {top}")

    # ------------------------------------------------------- 2) recall y MRR
    n = len(resultados)
    print("\n" + "=" * 100)
    print("2) RECALL@k (casos con al menos un esperado en el top k) y MRR")
    print("=" * 100)
    for k in (1, 3, 5, 10, 20):
        hits = sum(1 for r in resultados if r["rank"] and r["rank"] <= k)
        print(f"   recall@{k:<2} = {hits}/{n} = {hits / n:.0%}")
    mrr = sum(1 / r["rank"] for r in resultados if r["rank"]) / n
    print(f"   MRR      = {mrr:.3f}")
    print(f"   candidatos por caso: mediana {statistics.median(len(r['res']) for r in resultados):.0f}"
          f" | tiempo por caso: mediana {statistics.median(tiempos):.2f}s, máx {max(tiempos):.2f}s")
    fallan = [r["caso"]["id"] for r in resultados if not r["rank"] or r["rank"] > TOP_K]
    print(f"   Fuera del top {TOP_K}: {', '.join(fallan) or '(ninguno)'}")

    # ------------------------------------------------------- 3) distribución
    rel = [m["score"] for r in resultados for m in r["res"] if m["ok"]]
    norel = [m["score"] for r in resultados for m in r["res"][:10] if not m["ok"]]
    top1 = [r["res"][0]["score"] for r in resultados if r["res"]]
    bas = [b["res"][0]["score"] for b in basura if b["res"]]
    print("\n" + "=" * 100)
    print("3) DISTRIBUCIÓN DE SCORES (p10 / mediana / p90 / max)")
    print("=" * 100)
    for nombre, v in (("relevantes", rel), ("no relevantes (top10)", norel),
                      ("top1 de casos", top1), ("top1 de basura", bas)):
        if v:
            print(f"   {nombre:<24} n={len(v):<4} p10={pct(v, .1):.3f}  med={statistics.median(v):.3f}  "
                  f"p90={pct(v, .9):.3f}  max={max(v):.3f}")
    for b in basura:
        print(f"   basura: {b['query'][:45]:<45} top1={b['res'][0]['etiqueta']}({b['res'][0]['score']:.3f})")

    # ---------------------------------------------------- 4) barrido umbral
    print("\n" + "=" * 100)
    print(f"4a) UMBRAL ABSOLUTO sobre el top {TOP_K}: lo que sobrevive al filtro")
    print("    casos_ok = casos que conservan al menos 1 esperado | precisión = esperados/retenidos")
    print("    basura   = consultas basura que dejan pasar algo (debería ser 0)")
    print("=" * 100)
    print("   umbral  casos_ok  vacíos  retenidos  precisión  basura")
    lo = min(rel + norel + bas) if rel else 0.0
    hi = max(top1 + bas) if top1 else 1.0
    t = round(lo - lo % 0.02, 2)
    while t <= hi + 0.02:
        ok = vacios = ret = buenos = 0
        for r in resultados:
            kept = [m for m in r["res"][:TOP_K] if m["score"] >= t]
            ret += len(kept)
            buenos += sum(m["ok"] for m in kept)
            ok += any(m["ok"] for m in kept)
            vacios += not kept
        bpasa = sum(1 for b in basura if any(x["score"] >= t for x in b["res"]))
        prec = buenos / ret if ret else float("nan")
        print(f"   {t:.2f}    {ok:>3}/{n:<3}  {vacios:>4}    {ret:>5}      {prec:>5.0%}     {bpasa}/{len(basura)}")
        t = round(t + 0.02, 2)

    print("\n" + "=" * 100)
    print(f"4b) UMBRAL RELATIVO sobre el top {TOP_K}: conservar si score >= top1 - delta")
    print("=" * 100)
    print("   delta  retenidos  precisión  esperados_perdidos")
    for delta in (0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 1.0):
        ret = buenos = perdidos = 0
        for r in resultados:
            if not r["res"]:
                continue
            corte = r["res"][0]["score"] - delta
            top = r["res"][:TOP_K]
            kept = [m for m in top if m["score"] >= corte]
            ret += len(kept)
            buenos += sum(m["ok"] for m in kept)
            perdidos += sum(m["ok"] for m in top if m["score"] < corte)
        print(f"   {delta:<5}  {ret:>6}     {buenos / ret:>5.0%}       {perdidos}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"casos": resultados, "basura": basura}, f, ensure_ascii=False, indent=1)
        print(f"\nResultados crudos en {args.json}")


if __name__ == "__main__":
    main()
