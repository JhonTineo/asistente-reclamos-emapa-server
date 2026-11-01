# -*- coding: utf-8 -*-
"""Evalúa la búsqueda normativa contra un gold set (gold_busqueda.json).

Responde a tres preguntas:
  1. ¿Qué parámetros (top_k, umbral de score) dan búsquedas precisas?
  2. ¿Qué modelo de embeddings recupera mejor los artículos que aplican?
  3. ¿La búsqueda trae como mínimo los artículos usados en reclamos anteriores?

Cada colección se evalúa por separado (reclamos y calidad), con el corpus tal
como queda indexado: reclamos con `reclamos_chunker`; calidad con `calidad_chunker`
(`--calidad actual` reproduce el índice anterior: pdf_chunk + split_numerals).

No necesita Qdrant: los vectores se comparan con coseno en memoria (igual que
Distance.COSINE). Modos:

  # línea base léxica (BM25), sin red: valida chunks y etiquetas
  python -m app.test.rag.evaluar_busqueda --modo lexico

  # embeddings reales con Ollama (los modelos deben estar descargados: ollama pull ...)
  python -m app.test.rag.evaluar_busqueda --modo embeddings \
      --modelos nomic-embed-text,bge-m3,embeddinggemma,qwen3-embedding:0.6b --prefijos auto

  # el mismo modelo con y sin prefijos de tarea
  python -m app.test.rag.evaluar_busqueda --modo embeddings --modelos nomic-embed-text --prefijos ninguno
  python -m app.test.rag.evaluar_busqueda --modo embeddings --modelos nomic-embed-text --prefijos nomic

  "--modelos hash" usa un embedder de prueba (sin red) solo para verificar el harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass

import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)

from app.src.application.services.rag.index_reclamos import PDF_RECLAMOS_POR_DEFECTO
from app.src.application.services.rag.legal_chunker import split_numerals
from app.src.application.services.rag.normativa_escalonada import CATALOGO
from app.src.application.services.rag.pdf_chunk import clean_article, extract_document_structure, parse_document
from app.src.application.services.rag.calidad_chunker import chunkear_calidad
from app.src.application.services.rag.reclamos_chunker import NORMA_CORTA, chunkear_reclamos
from app.src.application.usecase.agents.fundamentacion_normativa import FundamentacionNormativaAgent
from app.src.core.model.informe_atencion import ProblemaNormado

GOLD = os.path.join(os.path.dirname(__file__), "gold_busqueda.json")
PDF_CALIDAD = os.path.join(
    REPO_ROOT, "app", "src", "storage", "files", "RESOLUCIÓN N_º 058-2023-SUNASS-CD-5-36.pdf"
)
RECLAMOS, CALIDAD = "sunass_reclamos", "sunass_reglamento"
KS = (1, 3, 5, 8)
UMBRALES = (0.45, 0.50, 0.55, 0.58, 0.60, 0.62, 0.65, 0.70, 0.72, 0.74, 0.76, 0.78, 0.80)
PREFIJOS = {
    "ninguno": ("", ""),
    "nomic": ("search_query: ", "search_document: "),
    "e5": ("query: ", "passage: "),
    # Prompts oficiales de la ficha de cada modelo.
    "gemma": ("task: search result | query: ", "title: none | text: "),
    "qwen3": ("Instruct: Given a question about a water utility claim, retrieve the regulation "
              "article that answers it\nQuery: ", ""),
}


def prefijo_por_defecto(modelo: str) -> str:
    """Nombre del juego de prefijos que recomienda la ficha de cada familia de modelos
    (bge-m3 no usa ninguno)."""
    for clave, nombre in (("nomic", "nomic"), ("e5", "e5"), ("gemma", "gemma"), ("qwen3", "qwen3")):
        if clave in modelo:
            return nombre
    return "ninguno"


# --------------------------------------------------------------------------- #
# Corpus
# --------------------------------------------------------------------------- #
@dataclass
class Doc:
    id: str
    coleccion: str
    article: str
    numeral: str | None
    texto: str
    texto_embedding: str


def corpus_reclamos(variante: str = "cuerpo", sin_anexos: bool = False) -> list[Doc]:
    """`variante` = qué texto se vectoriza: 'cuerpo' (el de index_reclamos: sin el encabezado
    "Artículo N.- Título"), 'texto' (artículo + texto) o 'completo' (además, norma + título +
    capítulo: la primera versión, que midió peor)."""
    docs = []
    for c in chunkear_reclamos(PDF_RECLAMOS_POR_DEFECTO):
        if sin_anexos and c.tipo_unidad == "anexo":
            continue
        ubicacion = ". ".join(x for x in (NORMA_CORTA, c.titulo, c.capitulo) if x)
        emb = {"cuerpo": c.texto_embedding(), "texto": c.text,
               "completo": f"{ubicacion}.\n{c.text}"}[variante]
        docs.append(Doc(c.point_id(), RECLAMOS, c.article, c.numeral, c.text, emb))
    return docs


def corpus_calidad_nuevo() -> list[Doc]:
    """Calidad con `calidad_chunker` (ligaturas reparadas, preámbulos conservados, sin
    fragmentos): lo que contiene hoy `sunass_reglamento`."""
    return [
        Doc(c.point_id(), CALIDAD, c.article, c.numeral, c.text, c.texto_embedding())
        for c in chunkear_calidad(PDF_CALIDAD)
    ]


def corpus_calidad() -> list[Doc]:
    """Como está en el Qdrant de desarrollo: mismo troceo, 266 puntos. Los fragmentos
    espurios ("93.1 y") conviven con los numerales reales porque ese índice se creó con
    ids aleatorios; con el código actual (ids uuid5) se pisarían al reindexar."""
    articulos = [clean_article(a) for a in parse_document(extract_document_structure(PDF_CALIDAD))]
    puntos: list[Doc] = []
    for a in articulos:
        m = re.search(r"ART[IÍ]CULO\s+(\d+)", a["articulo"], re.IGNORECASE)
        numero = m.group(1) if m else None
        for ch in split_numerals(numero, (a["articulo"] + "\n" + a["texto"]).strip()):
            puntos.append(Doc(str(len(puntos)), CALIDAD, str(ch["article"]), ch["numeral"], ch["text"], ch["text"]))
    return puntos


# --------------------------------------------------------------------------- #
# Rankers
# --------------------------------------------------------------------------- #
_STOP = set(
    "de la el en y a los las del que se por un una con para al lo su sus es o como mas son sin sobre "
    "este esta estos estas ser han ha le les ni si no entre cuando donde cual cuales".split()
)


def _tokens(texto: str) -> list[str]:
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    salida = []
    for t in re.findall(r"[a-z0-9]+", texto):
        if t in _STOP or len(t) < 2:
            continue
        salida.append(t[:-1] if len(t) > 4 and t.endswith("s") else t)
    return salida


class Lexico:
    """BM25: línea base sin red. Sus puntajes NO son comparables con coseno."""
    nombre = "bm25"
    es_coseno = False

    def __init__(self, docs: list[Doc], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.tf = [Counter(_tokens(d.texto_embedding)) for d in docs]
        self.dl = [sum(c.values()) for c in self.tf]
        self.avg = sum(self.dl) / len(docs)
        df: Counter = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def buscar(self, consulta: str, k: int) -> list[tuple[Doc, float]]:
        q = _tokens(consulta)
        puntajes = []
        for c, dl in zip(self.tf, self.dl):
            s = 0.0
            for t in q:
                f = c.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            puntajes.append(s)
        orden = np.argsort(puntajes)[::-1][:k]
        return [(self.docs[i], float(puntajes[i])) for i in orden]


class QdrantRanker:
    """Consulta una colección del Qdrant EN VIVO por el camino de producción
    (Retriever -> EmbeddingService.encode_query -> QdrantAdapter.search), con los
    vectores que están guardados. Mide el sistema tal como corre."""
    es_coseno = True

    def __init__(self, coleccion: str, sin_anexos: bool = False):
        from app.src.application.services.rag.retriever import Retriever
        from app.src.infrastructure.adapters.qdrant_adapter import QdrantAdapter
        self.nombre = self.coleccion = coleccion
        self.sin_anexos = sin_anexos
        self.retriever = Retriever(QdrantAdapter())

    def buscar(self, consulta: str, k: int) -> list[tuple[Doc, float]]:
        salida = []
        # Con sin_anexos se pide de más porque se descartan después (14 chunks de anexo).
        for r in self.retriever.retrieve(consulta, top_k=k + (14 if self.sin_anexos else 0), collection_name=self.coleccion):
            p = r["payload"]
            if self.sin_anexos and p.get("tipo_unidad") == "anexo":
                continue
            texto = p.get("text", "")
            salida.append((Doc(str(r["id"]), self.coleccion, str(p.get("article")), p.get("numeral"), texto, texto), r["score"]))
        return salida[:k]


class _Hash:
    """Embedder de prueba (bolsa de palabras hasheada). Solo valida el harness."""
    def _vec(self, texto: str) -> list[float]:
        v = np.zeros(512)
        for t in _tokens(texto):
            v[int(hashlib.md5(t.encode()).hexdigest(), 16) % 512] += 1
        return v.tolist()

    def embed_documents(self, textos): return [self._vec(t) for t in textos]
    def embed_query(self, texto): return self._vec(texto)


class Embeddings:
    es_coseno = True

    def __init__(self, modelo: str, docs: list[Doc], prefijo_q: str, prefijo_d: str, base_url: str):
        self.nombre, self.docs, self.prefijo_q = modelo, docs, prefijo_q
        if modelo == "hash":
            self.emb = _Hash()
        else:
            from langchain_ollama import OllamaEmbeddings
            self.emb = OllamaEmbeddings(model=modelo, base_url=base_url)
        textos = [prefijo_d + d.texto_embedding for d in docs]
        vecs: list = []
        for i in range(0, len(textos), 16):
            vecs += self.emb.embed_documents(textos[i:i + 16])
        m = np.array(vecs, dtype=float)
        self.m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)

    def buscar(self, consulta: str, k: int) -> list[tuple[Doc, float]]:
        v = np.array(self.emb.embed_query(self.prefijo_q + consulta), dtype=float)
        v = v / max(np.linalg.norm(v), 1e-12)
        sims = self.m @ v
        orden = np.argsort(sims)[::-1][:k]
        return [(self.docs[i], float(sims[i])) for i in orden]


# --------------------------------------------------------------------------- #
# Evaluación
# --------------------------------------------------------------------------- #
def consulta_para(caso: dict, fuente: str) -> str:
    """La misma consulta que arma el agente de fundamentación para esa norma."""
    if caso.get("consulta"):
        return caso["consulta"]
    return FundamentacionNormativaAgent._construir_query(
        ProblemaNormado(tipo=caso["tipo"], detalle=caso["detalle"]), caso.get("motivo", ""), CATALOGO[fuente]
    )


def _coincide(doc: Doc, esp: dict) -> bool:
    return doc.article == esp["article"] and doc.numeral == esp["numeral"]


def evaluar(ranker, casos: list[dict], fuente: str, nombre: str | None = None) -> dict:
    """`fuente` es la colección DEL GOLD contra la que se puntúa (RECLAMOS o
    CALIDAD); `nombre` permite evaluar otra colección equivalente (p. ej. el
    reglamento de reclamos 2019) con las mismas etiquetas."""
    filas = []
    for caso in casos:
        esperados = [e for e in caso["esperados"] if e["coleccion"] == fuente]
        res = ranker.buscar(consulta_para(caso, fuente), max(KS))
        rangos = [next((i + 1 for i, (d, _) in enumerate(res) if _coincide(d, e)), None) for e in esperados]
        filas.append({
            "id": caso["id"], "esperados": esperados, "rangos": rangos,
            "top1": f"{res[0][0].article}/{res[0][0].numeral}" if res else None,
            "top1_score": res[0][1] if res else 0.0,
            "top_k_scores": [s for _, s in res], "top_k_ids": [(d.article, d.numeral) for d, _ in res],
        })
    con = [f for f in filas if f["esperados"]]
    sin = [f for f in filas if not f["esperados"]]
    out = {"fuente": nombre or fuente, "n": len(con), "n_sin_esperados": len(sin), "filas": filas, "por_k": {}, "umbral": {}}
    for k in KS:
        hits = [any(r is not None and r <= k for r in f["rangos"]) for f in con]
        recalls = [sum(r is not None and r <= k for r in f["rangos"]) / len(f["esperados"]) for f in con]
        out["por_k"][k] = {"hit": float(np.mean(hits)) if con else None, "recall": float(np.mean(recalls)) if con else None}
    primeros = [min((r for r in f["rangos"] if r), default=None) for f in con]
    out["mrr"] = float(np.mean([1 / r if r else 0 for r in primeros])) if con else None
    if ranker.es_coseno:
        # ¿Hay un umbral absoluto que separe lo relevante de lo ajeno? Compara el top-1
        # de los aciertos con el de las consultas fuera de ámbito (casos 'negativo_*').
        aciertos = [f["top1_score"] for f in con if f["rangos"] and f["rangos"][0] == 1]
        negativos = [f["top1_score"] for f in sin if f["id"].startswith("negativo_")]
        out["separacion"] = {
            "aciertos_top1_min": min(aciertos) if aciertos else None,
            "aciertos_top1_mediana": float(np.median(aciertos)) if aciertos else None,
            "negativos_top1_max": max(negativos) if negativos else None,
        }
        for u in UMBRALES:
            rec3 = []
            for f in con:
                halladas = sum(1 for r in f["rangos"] if r is not None and r <= 3 and f["top_k_scores"][r - 1] >= u)
                rec3.append(halladas / len(f["esperados"]))
            fp = [f["top1_score"] >= u for f in sin]
            out["umbral"][u] = {
                "cobertura": float(np.mean([f["top1_score"] >= u for f in con])) if con else None,
                "recall@3": float(np.mean(rec3)) if con else None,
                "falsos_positivos": float(np.mean(fp)) if fp else None,
            }
    return out


def _pct(x) -> str:
    return "  -  " if x is None else f"{100 * x:5.1f}"


def imprimir(nombre: str, resultados: dict[str, dict], detalle: bool) -> None:
    print(f"\n### {nombre}")
    for fuente, r in resultados.items():
        print(f"\n**{fuente}** — {r['n']} casos con artículos esperados, {r['n_sin_esperados']} sin esperados (negativos / de la otra norma)")
        print("| k | hit@k % | recall@k % |")
        print("|---|---------|------------|")
        for k, m in r["por_k"].items():
            print(f"| {k} | {_pct(m['hit'])} | {_pct(m['recall'])} |")
        print(f"MRR = {r['mrr']:.3f}" if r["mrr"] is not None else "MRR = -")
        sep = r.get("separacion")
        if sep and sep["negativos_top1_max"] is not None and sep["aciertos_top1_mediana"] is not None:
            print(f"Separación de scores: aciertos top-1 mediana={sep['aciertos_top1_mediana']:.3f} "
                  f"(mín {sep['aciertos_top1_min']:.3f}) | consulta ajena top-1 máx={sep['negativos_top1_max']:.3f}")
        if r["umbral"]:
            print("\n| umbral | cobertura top-1 % | recall@3 con umbral % | falsos positivos top-1 % |")
            print("|--------|-------------------|-----------------------|--------------------------|")
            for u, m in r["umbral"].items():
                print(f"| {u:.2f} | {_pct(m['cobertura'])} | {_pct(m['recall@3'])} | {_pct(m['falsos_positivos'])} |")
        fallos = [f for f in r["filas"] if f["esperados"] and not any(x is not None and x <= 3 for x in f["rangos"])]
        if fallos:
            print("\nNo recuperados en el top-3: " + ", ".join(f"`{f['id']}` (top1={f['top1']})" for f in fallos))
        if detalle:
            for f in r["filas"]:
                print(f"  {f['id']:45} esperados={[(e['article'], e['numeral']) for e in f['esperados']]} "
                      f"rangos={f['rangos']} top1={f['top1']} score={f['top1_score']:.3f}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=("lexico", "embeddings", "qdrant"), default="lexico",
                    help="qdrant = consulta las colecciones EN VIVO como lo hace la app")
    ap.add_argument("--modelos", default="nomic-embed-text")
    ap.add_argument("--prefijos", choices=("auto", *PREFIJOS), default="auto")
    ap.add_argument("--ollama", default=os.getenv("OLLAMA_BASE_URL_EVAL") or "http://localhost:11434")
    ap.add_argument("--detalle", action="store_true")
    ap.add_argument("--texto-reclamos", choices=("cuerpo", "texto", "completo"), default="cuerpo",
                    help="qué texto se vectoriza en la colección de reclamos (modo embeddings)")
    ap.add_argument("--sin-anexos", action="store_true", help="excluye los chunks de anexo de reclamos")
    ap.add_argument("--calidad", choices=("actual", "nuevo"), default="nuevo",
                    help="nuevo = calidad_chunker, lo que está indexado hoy (por defecto); "
                         "actual = el índice anterior (pdf_chunk), solo para reproducir las cifras viejas")
    ap.add_argument("--salida", help="JSON con todas las métricas")
    args = ap.parse_args()

    casos = json.load(open(GOLD, encoding="utf-8"))["casos"]
    todo: dict[str, dict] = {}

    if args.modo == "qdrant":
        # (colección en Qdrant, colección del gold con que se puntúa)
        objetivos = [(RECLAMOS, RECLAMOS), (CALIDAD, CALIDAD)]
        resultados = {}
        for coleccion, fuente_gold in objetivos:
            try:
                resultados[coleccion] = evaluar(
                    QdrantRanker(coleccion, sin_anexos=args.sin_anexos and coleccion == RECLAMOS),
                    casos, fuente_gold, nombre=coleccion)
            except Exception as e:
                print(f"\n### {coleccion}: no se pudo evaluar ({type(e).__name__}: {e})")
        etiqueta = "PRODUCCIÓN: Qdrant en vivo, mismo camino que Yumi"
        imprimir(etiqueta, resultados, args.detalle)
        todo[etiqueta] = {f: {k: v for k, v in r.items() if k != "filas"} for f, r in resultados.items()}
        if args.salida:
            json.dump(todo, open(args.salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
            print("\nJSON escrito en", args.salida)
        return 0

    corpus = {RECLAMOS: corpus_reclamos(args.texto_reclamos, args.sin_anexos),
              CALIDAD: corpus_calidad_nuevo() if args.calidad == "nuevo" else corpus_calidad()}
    print(f"Corpus: {RECLAMOS}={len(corpus[RECLAMOS])} chunks, {CALIDAD}={len(corpus[CALIDAD])} puntos (como está indexado hoy) | casos={len(casos)}")

    configuraciones = [("bm25", None)] if args.modo == "lexico" else [(m.strip(), m.strip()) for m in args.modelos.split(",")]
    for nombre, modelo in configuraciones:
        if modelo is None:
            rankers = {f: Lexico(d) for f, d in corpus.items()}
            etiqueta = "BM25 (línea base léxica)"
        else:
            pref = args.prefijos
            if pref == "auto":
                pref = prefijo_por_defecto(modelo)
            pq, pd = PREFIJOS[pref]
            try:
                rankers = {f: Embeddings(modelo, d, pq, pd, args.ollama) for f, d in corpus.items()}
            except Exception as e:
                print(f"\n### {modelo}: no se pudo evaluar ({type(e).__name__}: {e})")
                continue
            etiqueta = f"{modelo} (prefijos: {pref})"
        resultados = {f: evaluar(rankers[f], casos, f) for f in corpus}
        imprimir(etiqueta, resultados, args.detalle)
        todo[etiqueta] = {f: {k: v for k, v in r.items() if k != "filas"} for f, r in resultados.items()}

    if args.salida:
        json.dump(todo, open(args.salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        print("\nJSON escrito en", args.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
