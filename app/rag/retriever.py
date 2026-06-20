from app.rag.embeddings import (
    EmbeddingService
)

from app.rag.qdrant_store import (
    QdrantStore
)


class RegulationRetriever:

    def __init__(self):

        self.embedder = (
            EmbeddingService()
        )

        self.store = (
            QdrantStore()
        )

    def retrieve(
        self,
        query: str,
        top_k: int = 5
    ):

        vector = self.embedder.encode(
            query
        )

        return self.store.search(
            vector,
            top_k=top_k
        )
    
    def build_context(
    self,
    results
    ):

        context = []

        for r in results:

            payload = r["payload"]

            context.append(
                f"""
    Artículo:
    {payload.get('article','')}

    Numeral:
    {payload.get('numeral','')}

    Texto:
    {payload.get('text','')}
    """
            )

        return "\n\n".join(context)