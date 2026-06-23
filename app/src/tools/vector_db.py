import os
import logging
from typing import Iterable, List, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)


def get_client() -> QdrantClient:
    return QdrantClient(
        url=os.getenv(
            "QDRANT_URL",
            "http://127.0.0.1:6335"
        )
    )


class QdrantStore:

    def __init__(self, collection_name=None, dim=768):

        self.collection_name = (
            collection_name
            or os.getenv(
                "QDRANT_COLLECTION_NAME",
                "sunass_reglamento"
            )
        )

        self.client = get_client()
        self.dim = dim

    def create_collection(self):

        try:
            self.client.delete_collection(
                collection_name=self.collection_name
            )
        except Exception:
            pass

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=qmodels.VectorParams(
                size=self.dim,
                distance=qmodels.Distance.COSINE
            )
        )

        logger.info(
            "Collection creada: %s",
            self.collection_name
        )

    def upsert(self, points):

        qdrant_points = []

        for p in points:

            qdrant_points.append(
                qmodels.PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p["payload"]
                )
            )

        self.client.upsert(
            collection_name=self.collection_name,
            points=qdrant_points
        )

    def search(self, vector, top_k=5):

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
    def _get_client():
        return QdrantClient(
            url=os.getenv(
                "QDRANT_URL",
                "http://127.0.0.1:6335"
            )
        )