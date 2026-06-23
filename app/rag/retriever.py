# app/scripts/build_reclamos_index.py 

import logging 
from app.rag.embeddings import EmbeddingService 
from app.rag.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)
class Retriever:

    def __init__(self):

        self.embedder = EmbeddingService()
        self.store = QdrantStore()

    def retrieve(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5
    ):

        vector = self.embedder.encode(query)

        return self.store.search(
            collection_name=collection_name,
            vector=vector,
            top_k=top_k
        )

    def build_context(
        self,
        collection_name: str,
        results
    ):

        if collection_name == "sunass_reglamento":
            return self._build_regulation_context(results)

        if collection_name == "tipos_reclamos":
            return self._build_claim_context(results)

        return ""

    def _build_regulation_context(
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

    def _build_claim_context(
        self,
        results
    ):

        context = []

        for r in results:

            payload = r["payload"]

            context.append(
                f"""
Código:
{payload.get('codigo','')}

Categoría:
{payload.get('categoria','')}

Tipo:
{payload.get('tipo','')}

Subtipo:
{payload.get('subtipo','')}

Definición:
{payload.get('definicion','')}
"""
            )

        return "\n\n".join(context)