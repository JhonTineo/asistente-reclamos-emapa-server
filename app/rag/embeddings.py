import os

from sentence_transformers import (
    SentenceTransformer
)


class EmbeddingService:

    def __init__(self):

        model_name = os.getenv(
            "EMBEDDING_MODEL",
            "BAAI/bge-m3"
        )

        self.model = SentenceTransformer(
            model_name
        )

    def encode(self, text: str):

        embedding = self.model.encode(
            text,
            normalize_embeddings=True
        )

        return embedding.tolist()

    @property
    def dimension(self):

        return self.model.get_embedding_dimension()