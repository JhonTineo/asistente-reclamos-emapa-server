from rag.embeddings import (
    EmbeddingService
)

from rag.qdrant_store import (
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
        top_k: int = 5,
        collection_name: str | None = None
    ):

        vector = self.embedder.encode(
            query
        )

        return self.store.search(
            vector,
            top_k=top_k,
            collection_name=collection_name
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