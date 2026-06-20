import os

from qdrant_client import (
    QdrantClient
)

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
        dimension: int
    ):

        collections = self.client.get_collections()

        existing = [
            c.name
            for c in collections.collections
        ]

        if self.collection_name in existing:
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=dimension,
                distance=Distance.COSINE
            )
        )

    def upsert(
        self,
        points
    ):

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
            collection_name=self.collection_name,
            points=qdrant_points
        )

    def search(
        self,
        vector,
        top_k=5
    ):

        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            limit=top_k
        )

        return [
            {
                "id": r.id,
                "score": r.score,
                "payload": r.payload
            }
            for r in results
        ]

    def count(self):

        return self.client.count(
            collection_name=self.collection_name
        ).count