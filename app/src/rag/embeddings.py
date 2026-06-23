import os

from langchain_ollama import OllamaEmbeddings


class EmbeddingService:

    def __init__(self):

        base_url = os.getenv(
            "OLLAMA_BASE_URL",
            "http://ollama:11434"
        )

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