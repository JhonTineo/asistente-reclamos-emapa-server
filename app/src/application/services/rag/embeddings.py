"""Servicio de embeddings (Ollama), independiente del modelo.

Cada modelo de embedding espera que la QUERY y el DOCUMENTO se le presenten de
una forma concreta (prefijos / instrucción). Si no se respeta, el modelo rinde
bastante peor que en sus benchmarks: es lo que pasaba con nomic-embed-text,
que exige `search_query:` / `search_document:` y se usaba sin ellos.

  - encode(texto)        -> vector de DOCUMENTO (indexado de normativa).
  - encode_query(texto)  -> vector de CONSULTA (búsqueda).

La dimensión se detecta en tiempo de ejecución (no se asume 768), porque cambia
según el modelo (qwen3-embedding:0.6b y bge-m3 -> 1024).

IMPORTANTE: al cambiar de modelo hay que REINDEXAR (recrear) las colecciones;
vectores de modelos distintos no son comparables.
"""

import threading
from collections import OrderedDict

from langchain_ollama import OllamaEmbeddings

from app.src.infrastructure.config.settings import settings


# (prefijo_query, prefijo_documento) por familia de modelo. Se elige por
# coincidencia con el nombre del modelo configurado.
_QWEN3_INSTRUCCION = (
    "Instruct: Given a finding from a water and sanitation service customer "
    "complaint in Peru, retrieve the SUNASS regulation provisions that govern it\n"
    "Query: "
)

PERFILES_MODELO: dict[str, tuple[str, str]] = {
    "qwen3-embedding": (_QWEN3_INSTRUCCION, ""),
    "nomic-embed-text": ("search_query: ", "search_document: "),
    "multilingual-e5": ("query: ", "passage: "),
    "bge-m3": ("", ""),
    "snowflake-arctic-embed": ("query: ", ""),
}


def _perfil(modelo: str) -> tuple[str, str]:
    nombre = modelo.lower()
    for clave, perfil in PERFILES_MODELO.items():
        if clave in nombre:
            return perfil
    return ("", "")


def _keep_alive(valor: str | None) -> int | str | None:
    """Ollama acepta segundos (int, -1 = siempre) o una duración ("30m").
    Vacío = el valor por defecto de Ollama."""
    valor = (valor or "").strip()
    if not valor:
        return None
    try:
        return int(valor)
    except ValueError:
        return valor


def precalentar() -> None:
    """Carga el modelo de embeddings en Ollama antes de la primera búsqueda
    (se llama al arrancar, en segundo plano). Nunca falla: si Ollama no está,
    la primera búsqueda lo cargará como siempre."""
    import logging
    import time
    log = logging.getLogger("rag.embeddings")
    inicio = time.perf_counter()
    try:
        EmbeddingService().encode_query("precalentado")
        log.info("[EMBEDDINGS] Modelo %s cargado en Ollama (%.1fs)",
                 settings.ollama_embedding_model, time.perf_counter() - inicio)
    except Exception as exc:  # noqa: BLE001
        log.warning("[EMBEDDINGS] No se pudo precalentar %s: %s", settings.ollama_embedding_model, exc)


MAX_CACHE_CONSULTAS = 512   # ~1024 floats c/u: unos 4 MB como máximo


class EmbeddingService:

    _dimension_cache: dict[str, int] = {}
    # Compartido por todas las instancias (cada fundamentación crea la suya).
    _cache_consultas: "OrderedDict[tuple[str, str], tuple[float, ...]]" = OrderedDict()
    _lock_cache = threading.Lock()

    def __init__(self, model: str | None = None):
        self.model_name = model or settings.ollama_embedding_model
        self.prefijo_query, self.prefijo_documento = _perfil(self.model_name)
        self.model = OllamaEmbeddings(
            model=self.model_name,
            base_url=settings.ollama_base_url,
            keep_alive=_keep_alive(settings.ollama_embedding_keep_alive),
        )

    def encode(self, text: str) -> list[float]:
        """Vector de DOCUMENTO (para indexar)."""
        return self.model.embed_query(self.prefijo_documento + text)

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectores de DOCUMENTO en lote (más rápido para indexar)."""
        if not texts:
            return []
        return self.model.embed_documents(
            [self.prefijo_documento + t for t in texts]
        )

    def encode_query(self, text: str) -> list[float]:
        """Vector de CONSULTA (para buscar). El mismo texto con el mismo modelo
        da siempre el mismo vector, así que se guarda en memoria: regenerar la
        fundamentación de un caso no vuelve a pagar sus embeddings (~4 s cada
        uno con 1.5 CPUs)."""
        clave = (self.model_name, self.prefijo_query + text)
        with self._lock_cache:
            vector = self._cache_consultas.get(clave)
            if vector is not None:
                self._cache_consultas.move_to_end(clave)
                return list(vector)
        vector = self.model.embed_query(self.prefijo_query + text)
        with self._lock_cache:
            self._cache_consultas[clave] = tuple(vector)
            while len(self._cache_consultas) > MAX_CACHE_CONSULTAS:
                self._cache_consultas.popitem(last=False)
        return vector

    @property
    def dimension(self) -> int:
        if self.model_name not in self._dimension_cache:
            self._dimension_cache[self.model_name] = len(self.encode("dimension"))
        return self._dimension_cache[self.model_name]
