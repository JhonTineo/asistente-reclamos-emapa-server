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
        vector = self.embedder.encode(query)
        return self.store.search(
            vector,
            top_k=top_k,
            collection_name=collection_name
        )

    def build_context(
        self,
        collection_name: str,
        results
    ):
        if collection_name == "sunass_reglamento":
            return self._build_regulation_context(results)
        if collection_name in ("tipos_reclamos", "anexo1_tipos_reclamo"):
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