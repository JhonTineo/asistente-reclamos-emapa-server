import os

from langchain_ollama import OllamaEmbeddings

# Reutiliza el resolver del adaptador de chat: aplica el mismo fallback DNS
# (p.ej. "ollama" -> 127.0.0.1 fuera de Docker), para no depender de que
# OLLAMA_BASE_URL apunte a un host resoluble en este entorno.
from app.src.application.adapters.llm import _resolver_ollama_base_url


class EmbeddingService:

    def __init__(self):

        base_url = _resolver_ollama_base_url()

        model = os.getenv(
            "OLLAMA_EMBEDDING_MODEL",
            "nomic-embed-text"
        )

        self.model = OllamaEmbeddings(
            model=model,
            base_url=base_url
        )

    def encode(self, text: str):

        embedding = self.model.embed_query(text)

        return embedding

    @property
    def dimension(self):

        return 768