import logging

from langchain_ollama import OllamaEmbeddings
from app.src.infrastructure.config.settings import settings

logger = logging.getLogger(__name__)

# Dimensión histórica (nomic-embed-text). Solo se usa si no se puede consultar
# al modelo y no hay `embedding_dimension` configurada.
_DIMENSION_POR_DEFECTO = 768


class EmbeddingService:

    def __init__(self, model: str | None = None, base_url: str | None = None):

        # Antes se leía OLLAMA_EMBEDDING_MODEL con os.getenv, que no ve el .env
        # (solo pydantic-settings lo lee). `settings` cubre ambos orígenes.
        self.model_name = model or settings.ollama_embedding_model
        self.query_prefix = settings.embedding_query_prefix
        self.document_prefix = settings.embedding_document_prefix
        self._dimension = settings.embedding_dimension or None

        self.model = OllamaEmbeddings(
            model=self.model_name,
            base_url=base_url or settings.ollama_base_url
        )

    def encode(self, text: str):
        """Vector SIN prefijos (comportamiento histórico)."""

        embedding = self.model.embed_query(text)

        return embedding

    def encode_query(self, text: str):
        """Vector de una consulta, con el prefijo de consulta del modelo."""

        return self.model.embed_query(self.query_prefix + text)

    def encode_document(self, text: str):
        """Vector de UN documento, con el prefijo de documento del modelo. Para
        altas y ediciones sueltas; el indexado masivo usa `encode_documents`."""

        return self.model.embed_query(self.document_prefix + text)

    def encode_documents(self, texts: list[str]):
        """Vectores de varios documentos en una sola llamada (indexado por
        lotes), con el prefijo de documento del modelo."""

        if not texts:
            return []

        return self.model.embed_documents(
            [self.document_prefix + t for t in texts]
        )

    @property
    def dimension(self):

        if self._dimension is None:
            try:
                self._dimension = len(self.encode("dimension"))
            except Exception as e:
                logger.warning(
                    "No se pudo detectar la dimensión de '%s' (%s); se asume %d",
                    self.model_name, e, _DIMENSION_POR_DEFECTO,
                )
                return _DIMENSION_POR_DEFECTO

        return self._dimension
