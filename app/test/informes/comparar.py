"""Etapa 3b: compara el gold (informes reales) contra las salidas de la
herramienta y emite el reporte de evaluación.

Métricas OBJETIVAS (sin LLM, siempre):
  - Veredicto: matriz de confusión real vs generado (agregada sobre runs).
  - Estabilidad: ¿el veredicto de un mismo caso varía entre corridas?
  - Lectura del medidor: ¿la herramienta "vio" la lectura real (número
    distintivo) en los datos/resumen del medio? (señal de que consultó bien EMAPA)
  - Objetivos: vuelca los objetivos generados y marca los determinantes; alerta
    en casos FUNDADO sin ningún objetivo determinante (causa típica de un
    INFUNDADO equivocado).

Métricas SEMÁNTICAS (LLM-judge, opcional con --llm-judge, reusa get_llm):
  - Resumen del medio generado vs hechos reales (consistencia/cobertura/alucinación).
  - Conclusión generada vs razonamiento real (fuga, facturación, base legal).

Uso:
    python -m app.test.informes.comparar \
        --gold-dir app/test/informes/gold \
        --salidas-dir app/test/informes/salidas \
        --out app/test/informes/reporte.md \
        [--llm-judge]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict


# --- utilidades ----------------------------------------------------------
def _flatten_valores(obj) -> list[str]:
    """Aplana un dict/list anidado a la lista de sus valores escalares (str)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += _flatten_valores(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _flatten_valores(v)
    elif obj is not None:
        out.append(str(obj).strip().lower())
    return out


def _cargar_golds(gold_dir: str) -> dict[str, dict]:
    golds = {}
    for f in sorted(glob.glob(os.path.join(gold_dir, "*.json"))):
        g = json.load(open(f, encoding="utf-8"))
        golds[g["codreclamo"]] = g
    return golds


def _cargar_salidas(salidas_dir: str) -> dict[str, list[dict]]:
    porcaso: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(salidas_dir, "*.json"))):
        s = json.load(open(f, encoding="utf-8"))
        porcaso[str(s.get("codreclamo"))].append(s)
    return porcaso


def _gold_medios(gold: dict) -> dict[str, dict]:
    """medio_id -> {texto_real, hechos} para los puntos que son medios."""
    return {
        p["medio_id"]: {"texto_real": p["texto_real"], "hechos": p.get("hechos", {})}
        for p in gold["puntos"] if p.get("medio_id")
    }


def _lectura_vista(salida_medio: dict, lectura_real) -> bool | None:
    """¿La lectura real del medidor aparece en los datos/resumen del medio
    generado? None si el gold no tiene lectura."""
    if lectura_real is None:
        return None
    objetivo = str(int(lectura_real))
    hay = set(_flatten_valores(salida_medio.get("datos"))) | {
        (salida_medio.get("resumen") or "").lower()
    }
    if objetivo in hay:
        return True
    # También busca el número dentro del texto del resumen.
    return objetivo in (salida_medio.get("resumen") or "")


# --- LLM-judge (opcional) ------------------------------------------------
def _get_judge():
    from app.src.application.adapters.llm import get_llm
    return get_llm()


def _judge_resumen(llm, texto_real: str, hechos: dict, resumen_gen: str) -> dict:
    from langchain_core.messages import SystemMessage, HumanMessage
    system = (
        "Eres un evaluador. Comparas la DESCRIPCIÓN GENERADA de un medio probatorio "
        "contra la descripción REAL (y sus hechos) de un informe de EMAPA. "
        "Devuelve SOLO un JSON con: "
        "\"consistencia\" (1-5, ¿contradice hechos reales?), "
        "\"cobertura\" (1-5, ¿menciona los hechos clave?), "
        "\"alucinacion\" (1-5, 5=nada inventado), "
        "\"nota\" (frase breve)."
    )
    human = (
        f"HECHOS REALES: {json.dumps(hechos, ensure_ascii=False)}\n"
        f"DESCRIPCIÓN REAL: {texto_real}\n\n"
        f"DESCRIPCIÓN GENERADA: {resumen_gen}\n\nDevuelve SOLO el JSON."
    )
    return _invoke_json(llm, system, human)


def _judge_conclusion(llm, gold: dict, informe_gen: str) -> dict:
    from langchain_core.messages import SystemMessage, HumanMessage
    system = (
        "Eres un evaluador. Comparas la CONCLUSIÓN GENERADA contra la conclusión REAL "
        "de un informe de EMAPA. Devuelve SOLO un JSON con: "
        "\"veredicto_coincide\" (true/false), "
        "\"razonamiento\" (1-5, ¿mismo camino lógico: tipo de fuga y forma de facturar?), "
        "\"base_legal\" (1-5, ¿cita/uso correcto del Art. 88.3 cuando aplica?), "
        "\"nota\" (frase breve)."
    )
    human = (
        f"CONCLUSIÓN REAL: {gold['conclusion_real']}\n"
        f"HECHOS DE LA CONCLUSIÓN REAL: {json.dumps(gold.get('conclusion_hechos', {}), ensure_ascii=False)}\n"
        f"VEREDICTO REAL: {gold['veredicto_real']}\n\n"
        f"INFORME GENERADO (incluye conclusión): {informe_gen}\n\nDevuelve SOLO el JSON."
    )
    return _invoke_json(llm, system, human)


def _invoke_json(llm, system: str, human: str) -> dict:
    import re
    from langchain_core.messages import SystemMessage, HumanMessage
    try:
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        txt = resp.content or ""
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        return json.loads(m.group()) if m else {"error": "sin JSON", "raw": txt[:200]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


# --- reporte -------------------------------------------------------------
def comparar(gold_dir: str, salidas_dir: str, usar_llm: bool) -> dict:
    golds = _cargar_golds(gold_dir)
    salidas = _cargar_salidas(salidas_dir)
    llm = _get_judge() if usar_llm else None

    matriz = defaultdict(int)   # (real, gen) -> count
    casos = []

    for codreclamo, gold in golds.items():
        runs = salidas.get(codreclamo, [])
        if not runs:
            continue
        real = gold["veredicto_real"]
        gmedios = _gold_medios(gold)

        veredictos_gen = [r.get("veredicto_generado") for r in runs]
        for vg in veredictos_gen:
            matriz[(real, vg or "NULL")] += 1
        estable = len(set(veredictos_gen)) == 1

        # Análisis por run (medios + objetivos) sobre el primer run con datos.
        run0 = runs[0]
        medios_gen = run0.get("medios", {})
        objetivos = (run0.get("objetivos") or {}).get("objetivos", [])
        n_determinantes = sum(1 for o in objetivos if o.get("determinante"))

        # Chequeo lectura del medidor (usa inspeccion_externa o tarjeta_lectura).
        lectura_real = None
        for mid, gm in gmedios.items():
            if "lectura_m3" in gm["hechos"]:
                lectura_real = gm["hechos"]["lectura_m3"]
                break
        # OJO: ResumenMedio siempre trae la clave "error" (=None por defecto), así
        # que "error not in dict" nunca sirve; hay que mirar su valor (truthiness).
        lectura_ok = None
        for cand in ("tarjeta_lectura", "inspeccion_externa"):
            if cand in medios_gen and not medios_gen[cand].get("error"):
                lectura_ok = _lectura_vista(medios_gen[cand], lectura_real)
                if lectura_ok:
                    break

        # LLM-judge por medio comparado + conclusión.
        judges_medio = {}
        judge_concl = None
        if llm:
            for mid, gm in gmedios.items():
                mg = medios_gen.get(mid)
                if mg and not mg.get("error"):
                    judges_medio[mid] = _judge_resumen(llm, gm["texto_real"], gm["hechos"], mg.get("resumen", ""))
            informe_gen = (run0.get("conclusion") or {}).get("informe", "")
            if informe_gen:
                judge_concl = _judge_conclusion(llm, gold, informe_gen)

        casos.append({
            "codreclamo": codreclamo,
            "suministro": gold["suministro"],
            "veredicto_real": real,
            "veredictos_generados": veredictos_gen,
            "acierto": (real == veredictos_gen[0]) if veredictos_gen else None,
            "estable": estable,
            "n_objetivos": len(objetivos),
            "n_determinantes": n_determinantes,
            "alerta_fundado_sin_determinante": (real == "FUNDADO" and n_determinantes == 0),
            "lectura_real": lectura_real,
            "lectura_vista_por_herramienta": lectura_ok,
            "medios_reales": list(gmedios.keys()),
            "medios_generados": [m for m in medios_gen if "error" not in medios_gen.get(m, {})],
            "judge_medios": judges_medio,
            "judge_conclusion": judge_concl,
            "errores_run0": run0.get("errores", []),
        })

    aciertos = sum(1 for c in casos if c["acierto"])
    return {
        "n_casos": len(casos),
        "aciertos_veredicto": aciertos,
        "accuracy_veredicto": round(aciertos / len(casos), 3) if casos else None,
        "matriz_confusion": {f"{k[0]}->{k[1]}": v for k, v in matriz.items()},
        "casos": casos,
    }


def render_md(rep: dict) -> str:
    L = ["# Reporte de evaluación — Informe de Atención\n"]
    L.append(f"- Casos comparados: **{rep['n_casos']}**")
    L.append(f"- Aciertos de veredicto: **{rep['aciertos_veredicto']}/{rep['n_casos']}** "
             f"(accuracy = {rep['accuracy_veredicto']})\n")
    L.append("## Matriz de confusion (real -> generado)\n")
    for k, v in sorted(rep["matriz_confusion"].items()):
        L.append(f"- {k}: {v}")
    L.append("\n## Por caso\n")
    L.append("| sum | real | generado | acierto | estable | obj (det) | lectura vista | alerta |")
    L.append("|-----|------|----------|---------|---------|-----------|---------------|--------|")
    for c in rep["casos"]:
        gen = ",".join(str(v) for v in c["veredictos_generados"])
        alerta = "⚠ FUNDADO sin determinante" if c["alerta_fundado_sin_determinante"] else ""
        lect = {True: "sí", False: "NO", None: "-"}[c["lectura_vista_por_herramienta"]]
        L.append(f"| {c['suministro']} | {c['veredicto_real']} | {gen} | "
                 f"{'OK' if c['acierto'] else 'FALLA'} | {'si' if c['estable'] else 'NO'} | "
                 f"{c['n_objetivos']} ({c['n_determinantes']}) | {lect} | {alerta} |")
    # LLM-judge (si hay)
    if any(c["judge_conclusion"] for c in rep["casos"]):
        L.append("\n## LLM-judge — conclusión\n")
        L.append("| sum | veredicto_coincide | razonamiento | base_legal | nota |")
        L.append("|-----|--------------------|--------------|------------|------|")
        for c in rep["casos"]:
            j = c["judge_conclusion"] or {}
            L.append(f"| {c['suministro']} | {j.get('veredicto_coincide','-')} | "
                     f"{j.get('razonamiento','-')} | {j.get('base_legal','-')} | {j.get('nota','')} |")
    return "\n".join(L)


def main() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows: evita cp1252 en consola
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-dir", default="app/test/informes/gold")
    ap.add_argument("--salidas-dir", default="app/test/informes/salidas")
    ap.add_argument("--out", default="app/test/informes/reporte.md")
    ap.add_argument("--llm-judge", action="store_true", help="Evalúa descripción/conclusión con LLM")
    args = ap.parse_args()

    rep = comparar(args.gold_dir, args.salidas_dir, args.llm_judge)
    json_out = os.path.splitext(args.out)[0] + ".json"
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    md = render_md(rep)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)

    print(md)
    print(f"\nReporte: {args.out}  |  JSON: {json_out}")


if __name__ == "__main__":
    main()
