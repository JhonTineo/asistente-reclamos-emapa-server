from app.src.application.services.rag.embeddings import (EmbeddingService)
from app.src.application.ports.vector_db_port import PuertoBaseVectorial
import logging

logger = logging.getLogger(__name__)
class Retriever:

    def __init__(self, store: PuertoBaseVectorial):
        self.embedder = EmbeddingService()
        self.store = store

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        collection_name: str | None = None
    ):
        vector = self.embedder.encode_query(query)
        return self.store.search(
            vector,
            top_k=top_k,
            collection_name=collection_name
        )