"""Acceso a la base normativa al estilo de un agente de código: índice de
títulos, lectura del texto literal por ID y búsqueda léxica. Sin embeddings ni
Ollama: todo en memoria (los dos reglamentos son ~600 unidades).

- indice(): los títulos de los artículos agrupados por título/capítulo (~3k
  tokens). Es lo que el LLM recorre para decidir qué leer.
- leer(ids): el texto vigente de un artículo con sus numerales/literales.
- buscar_texto(consulta): BM25 sobre las unidades; encuentra frases exactas
  ("28 y 32 días") que un embedding difumina.
- documento(norma): reconstruye el reglamento completo desde las unidades.

Los índices se derivan de la base y se recalculan con `recargar()` cuando
cambia una unidad.
"""

import logging
import math
import re
import threading
import unicodedata
from collections import Counter
from pathlib import Path

from app.src.infrastructure.adapters.persistencia.sqlite_normativa_repository import (
    SqliteNormativaRepository, UnidadNormativa,
)

logger = logging.getLogger("normativa.catalogo")

_RAIZ_REPO = Path(__file__).resolve().parents[5]
RUTA_POR_DEFECTO = _RAIZ_REPO / "volumes" / "yumi_db" / "normativa.db"

_STOPWORDS = frozenset("""
a al ante bajo con contra de del desde durante e el en entre esta este hacia hasta la las le les lo los
mediante o para por que se segun sin sobre su sus tras u un una uno y ya no ni es son ser sera
como cual cuando donde mas o ha han caso dicha dicho dichos dichas presente misma mismo otro otra
""".split())


def ruta_base_normativa() -> str:
    from app.src.infrastructure.config.settings import settings
    configurada = (getattr(settings, "yumi_normativa_db_path", "") or "").strip()
    return configurada or str(RUTA_POR_DEFECTO)


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                         if unicodedata.category(c) != "Mn")
    return sin_tildes.lower()


def _tokens(texto: str) -> list[str]:
    """Palabras sin tildes ni stopwords, con un stemming mínimo (plural)."""
    salida = []
    for t in re.findall(r"[a-z0-9]+", _normalizar(texto)):
        if t in _STOPWORDS or len(t) < 2:
            continue
        if len(t) > 4 and t.endswith("es"):
            t = t[:-2]
        elif len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        salida.append(t)
    return salida


class _BM25:
    def __init__(self, documentos: list[list[str]], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in documentos]
        self.largos = [len(d) for d in documentos]
        self.promedio = (sum(self.largos) / len(self.largos)) if self.largos else 1.0
        df = Counter(t for d in self.docs for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def puntajes(self, consulta: list[str]) -> list[float]:
        terminos = set(consulta)
        salida = []
        for doc, largo in zip(self.docs, self.largos):
            s = 0.0
            for t in terminos:
                f = doc.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * largo / self.promedio))
            salida.append(s)
        return salida


class CatalogoNormativo:

    def __init__(self, repo: SqliteNormativaRepository):
        self.repo = repo
        self._lock = threading.RLock()
        self.recargar()

    # ------------------------------------------------------------------ #
    def recargar(self) -> None:
        """Recalcula los índices desde la base (tras importar o modificar)."""
        with self._lock:
            self.unidades: list[UnidadNormativa] = self.repo.unidades()
            self.por_id = {u.id: u for u in self.unidades}
            self.hijas: dict[str, list[UnidadNormativa]] = {}
            for u in self.unidades:
                if u.padre_id:
                    self.hijas.setdefault(u.padre_id, []).append(u)
            # Documento de búsqueda: título del artículo + texto (el título
            # aporta el tema a numerales que solo dicen "En este caso, ...").
            self._buscables = [u for u in self.unidades if u.texto.strip()]
            self._bm25 = _BM25([
                _tokens(f"{self._titulo_articulo(u)} {u.texto}") for u in self._buscables
            ])
            self._indice = self._construir_indice()
        logger.info("[NORMATIVA] Catálogo cargado: %d unidades, índice ≈%d tokens",
                    len(self.unidades), len(self._indice) // 4)

    def _titulo_articulo(self, u: UnidadNormativa) -> str:
        if u.tipo == "articulo":
            return u.titulo or ""
        padre = self.por_id.get(u.padre_id or "")
        return (padre.titulo if padre else "") or ""

    def _construir_indice(self) -> str:
        lineas: list[str] = []
        norma_actual = ruta_actual = None
        for u in self.unidades:
            if u.tipo != "articulo":
                continue
            if u.norma_id != norma_actual:
                norma_actual, ruta_actual = u.norma_id, None
                lineas.append(f"\n## {u.norma} [{u.norma_id}]")
            if u.ruta != ruta_actual:
                ruta_actual = u.ruta
                if u.ruta:
                    lineas.append(f"### {u.ruta}")
            subs = self.hijas.get(u.id, [])
            detalle = ""
            if subs:
                etiquetas = [s.numeral.split()[-1] if s.tipo == "literal" else s.numeral for s in subs]
                detalle = f" ({etiquetas[0]} a {etiquetas[-1]})" if len(etiquetas) > 1 else f" ({etiquetas[0]})"
            lineas.append(f"- {u.id}: {u.titulo or '(sin título)'}{detalle}")
        return "\n".join(lineas).strip()

    # ------------------------------------------------------------------ #
    # Herramientas
    # ------------------------------------------------------------------ #
    def indice(self) -> str:
        return self._indice

    def ids_articulos(self) -> set[str]:
        return {u.id for u in self.unidades if u.tipo == "articulo"}

    def leer(self, unidad_id: str) -> list[UnidadNormativa]:
        """Un artículo con todas sus unidades (en orden), o una unidad suelta.
        Omite la parte introductoria vacía de los artículos divididos."""
        u = self.por_id.get(unidad_id)
        if u is None:
            return []
        if u.tipo != "articulo":
            return [u]
        partes = [u] if u.texto.strip() else []
        return partes + self.hijas.get(u.id, [])

    def buscar_texto(self, consulta: str, k: int = 5) -> list[tuple[UnidadNormativa, float]]:
        puntajes = self._bm25.puntajes(_tokens(consulta))
        orden = sorted(range(len(puntajes)), key=lambda i: -puntajes[i])
        return [(self._buscables[i], puntajes[i]) for i in orden[:k] if puntajes[i] > 0]

    def documento(self, norma_id: str, fecha: str | None = None) -> str:
        """Reconstruye el reglamento (vigente hoy o a `fecha`) en markdown."""
        unidades = self.repo.unidades(norma_id, fecha) if fecha else [
            u for u in self.unidades if u.norma_id == norma_id]
        if not unidades:
            return ""
        lineas = [f"# {unidades[0].norma}"]
        ruta_actual = None
        for u in unidades:
            if u.tipo == "articulo":
                if u.ruta and u.ruta != ruta_actual:
                    ruta_actual = u.ruta
                    lineas.append(f"\n## {u.ruta}")
                lineas.append(f"\n**Artículo {u.articulo}.- {u.titulo or ''}**")
                if u.nota:
                    lineas.append(f"_{u.nota}_")
            if u.texto.strip():
                lineas.append(u.texto)
        return "\n".join(lineas)

    # ------------------------------------------------------------------ #
    @staticmethod
    def a_resultado(u: UnidadNormativa, score: float, origen: str) -> dict:
        """Misma forma que un resultado de Qdrant (Retriever.retrieve), para
        que la fundamentación y la evaluación no distingan el origen."""
        return {
            "id": u.id,
            "score": score,
            "coleccion": u.coleccion,
            "origen": origen,
            "payload": {
                "unidad_id": u.id,
                "norma": u.norma,
                "article": u.articulo,
                "numeral": u.numeral,
                "titulo_articulo": u.titulo,
                "text": u.texto,
                "dispositivos": u.dispositivos,
            },
        }


_catalogo: CatalogoNormativo | None = None
_catalogo_lock = threading.Lock()


def catalogo_normativo() -> CatalogoNormativo:
    """Catálogo único del proceso. Si la base está vacía (primer arranque, o un
    VPS recién desplegado), la carga desde los PDFs del repositorio: no requiere
    pasos manuales ni Ollama."""
    global _catalogo
    with _catalogo_lock:
        if _catalogo is None:
            repo = SqliteNormativaRepository(ruta_base_normativa())
            if repo.esta_vacia():
                from app.src.application.services.normativa.importar import importar_todo
                logger.info("[NORMATIVA] Base vacía: importando desde los PDFs del repositorio")
                importar_todo(repo)
            _catalogo = CatalogoNormativo(repo)
        return _catalogo
