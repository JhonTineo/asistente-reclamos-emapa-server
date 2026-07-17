import os
from qdrant_client import ( QdrantClient )
from qdrant_client.http.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    PointIdsList
)


class QdrantStore:
    def __init__(self):
        self.collection_name = os.getenv(
            "QDRANT_COLLECTION_NAME",
            "sunass_reglamento"
        )
        self.client = QdrantClient(
            url=os.getenv(
                "QDRANT_URL",
                "http://localhost:6333"
            )
        )

    def create_collection(
        self,
        collection_name: str,
        dimension: int
    ):
        collections = self.client.get_collections()
        existing = [
            c.name
            for c in collections.collections
        ]
        if collection_name in existing:
            return
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=dimension,
                distance=Distance.COSINE
            )
        )

    def upsert(
        self,
        points,
        collection_name: str | None = None
    ):
        target_collection = collection_name or self.collection_name
        qdrant_points = []
        for point in points:
            qdrant_points.append(
                PointStruct(
                    id=point["id"],
                    vector=point["vector"],
                    payload=point["payload"]
                )
            )
        self.client.upsert(
            collection_name=target_collection,
            points=qdrant_points
        )

    def search(
        self,
        vector,
        top_k=5,
        collection_name: str | None = None
    ):
        target_collection = collection_name or self.collection_name
        results = self.client.query_points(
            collection_name=target_collection,
            query=vector,
            limit=top_k
        )
        return [
            {
                "id": p.id,
                "score": p.score,
                "payload": p.payload
            }
            for p in results.points
        ]
    
    def count(self):
        return self.client.count(
            collection_name=self.collection_name
        ).count

    def get_by_id(
        self,
        point_id: str | int,
        collection_name: str | None = None
    ):
        target_collection = collection_name or self.collection_name
        try:
            points = self.client.retrieve(
                collection_name=target_collection,
                ids=[point_id],
                with_payload=True,
                with_vectors=False
            )
            if points:
                p = points[0]
                return {
                    "id": p.id,
                    "payload": p.payload
                }
        except Exception:
            pass
        return None

    def filter_by_article(
        self,
        article: str,
        numeral: str | None = None,
        collection_name: str | None = None
    ):
        target_collection = collection_name or self.collection_name
        conditions = [
            FieldCondition(
                key="article",
                match=MatchValue(value=str(article))
            )
        ]
        if numeral:
            conditions.append(
                FieldCondition(
                    key="numeral",
                    match=MatchValue(value=str(numeral))
                )
            )
        try:
            results, _ = self.client.scroll(
                collection_name=target_collection,
                scroll_filter=Filter(must=conditions),
                with_payload=True,
                with_vectors=False,
                limit=100
            )
            return [
                {
                    "id": p.id,
                    "payload": p.payload
                }
                for p in results
            ]
        except Exception:
            return []

    def delete_by_id(
        self,
        point_id: str | int,
        collection_name: str | None = None
    ):
        target_collection = collection_name or self.collection_name
        self.client.delete(
            collection_name=target_collection,
            points_selector=PointIdsList(points=[point_id])
        )

    def search_by_keyword(
        self,
        keyword: str,
        collection_name: str | None = None,
        top_k: int = 15
    ):
        target_collection = collection_name or self.collection_name
        import unicodedata

        def _normalize(s: str) -> str:
            if not s:
                return ""
            s = unicodedata.normalize('NFKD', str(s))
            return "".join(c for c in s if not unicodedata.combining(c)).lower()

        norm_keyword = _normalize(keyword)

        # 1. Búsqueda exacta (scroll por todos los puntos de la colección para subcadena sin importar mayúsculas/ tildes)
        exact_matches = []
        try:
            offset = None
            while True:
                results, next_offset = self.client.scroll(
                    collection_name=target_collection,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False
                )
                for p in results:
                    text = p.payload.get("text", "") if p.payload else ""
                    if norm_keyword in _normalize(text):
                        exact_matches.append({
                            "id": p.id,
                            "tipo_coincidencia": "exacta (palabra clave)",
                            "score": 1.0,
                            "payload": p.payload
                        })
                offset = next_offset
                if not offset or len(results) == 0:
                    break
        except Exception:
            pass

        # 2. Búsqueda semántica vectorial (embeddings) como complemento
        semantic_matches = []
        try:
            from app.src.application.services.rag.embeddings import EmbeddingService
            embedder = EmbeddingService()
            vector = embedder.encode(keyword)
            sem_results = self.search(vector=vector, top_k=top_k, collection_name=target_collection)
            exact_ids = {m["id"] for m in exact_matches}
            for p in sem_results:
                if p["id"] not in exact_ids and p.get("score", 0) > 0.45:
                    semantic_matches.append({
                        "id": p["id"],
                        "tipo_coincidencia": "semántica (similitud)",
                        "score": round(float(p.get("score", 0)), 4),
                        "payload": p.get("payload", {})
                    })
        except Exception:
            pass

        return exact_matches + semantic_matches