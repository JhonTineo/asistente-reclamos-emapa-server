import os
from qdrant_client import ( QdrantClient )
from qdrant_client.http.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue
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
        
    def collection_exists(self, collection_name: str) -> bool:
        try:
            collections = self.client.get_collections()
            return collection_name in [c.name for c in collections.collections]
        except Exception:
            return False

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
        query_filter = Filter(
            must_not=[
                FieldCondition(
                    key="estado",
                    match=MatchValue(value="inactivo")
                )
            ]
        )
        results = self.client.query_points(
            collection_name=target_collection,
            query=vector,
            query_filter=query_filter,
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
        
    def delete(self, point_id: str, collection_name: str | None = None):
        target_collection = collection_name or self.collection_name
        self.client.set_payload(
            collection_name=target_collection,
            payload={"estado": "inactivo"},
            points=[point_id]
        )
        
    def get_all(self, collection_name: str | None = None):
        target_collection = collection_name or self.collection_name
        points = []
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
                    points.append({
                        "id": p.id,
                        "payload": p.payload
                    })
                offset = next_offset
                if not offset or len(results) == 0:
                    break
        except Exception:
            pass
        return points

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

        # 1. Búsqueda exacta
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
                    payload = p.payload or {}
                    if payload.get("estado") == "inactivo":
                        continue
                    texto = payload.get("text", "") or payload.get("texto", "")
                    articulo = payload.get("article", "") or payload.get("articulo", "")
                    numeral = payload.get("numeral", "")
                    pclaves = payload.get("palabras_clave", [])
                    palabras_clave = ", ".join(pclaves) if isinstance(pclaves, list) else str(pclaves)
                    
                    contenido = f"{texto} {articulo} {numeral} {palabras_clave}"
                    
                    if norm_keyword in _normalize(contenido):
                        exact_matches.append({
                            "id": p.id,
                            "tipo_coincidencia": "exacta (palabra clave)",
                            "score": 1.0,
                            "payload": payload
                        })
                offset = next_offset
                if not offset or len(results) == 0:
                    break
        except Exception:
            pass

        # 2. Búsqueda semántica vectorial
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