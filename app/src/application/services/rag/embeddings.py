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


class EmbeddingService:

    _dimension_cache: dict[str, int] = {}

    def __init__(self, model: str | None = None):
        self.model_name = model or settings.ollama_embedding_model
        self.prefijo_query, self.prefijo_documento = _perfil(self.model_name)
        self.model = OllamaEmbeddings(
            model=self.model_name,
            base_url=settings.ollama_base_url,
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
        """Vector de CONSULTA (para buscar)."""
        return self.model.embed_query(self.prefijo_query + text)

    @property
    def dimension(self) -> int:
        if self.model_name not in self._dimension_cache:
            self._dimension_cache[self.model_name] = len(self.encode("dimension"))
        return self._dimension_cache[self.model_name]
