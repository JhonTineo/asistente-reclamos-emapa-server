import os

from langchain_ollama import OllamaEmbeddings
from app.src.infrastructure.config.settings import settings


class EmbeddingService:

    def __init__(self):

        base_url = settings.ollama_base_url

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