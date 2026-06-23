import os

from qdrant_client import QdrantClient

from qdrant_client.http.models import (
    Distance,
    VectorParams,
    PointStruct
)


class QdrantStore:

    def __init__(self):

        self.client = QdrantClient(
            url=os.getenv(
                "QDRANTQDRANT_URL_URL",
                "http://127.0.0.1:6333"
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
        collection_name: str,
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

        points = getattr(results, "points", results)

        return [
            {
                "id": p.id,
                "score": p.score,
                "payload": p.payload
            }
            for p in results.points
        ]

    def count(
        self,
        collection_name: str
    ):

        return self.client.count(
            collection_name=collection_name
        ).count

    def collection_exists(
        self,
        collection_name: str
    ) -> bool:

        collections = self.client.get_collections()

        existing = {
            c.name
            for c in collections.collections
        }

        return collection_name in existing