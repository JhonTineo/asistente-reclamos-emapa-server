import os
from qdrant_client import ( QdrantClient )
from qdrant_client.http.models import (
    Distance,
    VectorParams,
    PointStruct
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