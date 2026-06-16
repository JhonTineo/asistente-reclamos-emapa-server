import os
import logging
from typing import Iterable, List, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

logger = logging.getLogger("tools.vector_db")


def _get_client() -> QdrantClient:
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY") or None
    return QdrantClient(url=url, api_key=api_key)


class QdrantStore:
    def __init__(self, collection_name: str | None = None, dim: int = 384):
        self.client = _get_client()
        self.collection = collection_name or os.getenv("QDRANT_COLLECTION_NAME", "normativas-sunass")
        self.dim = dim

    def create_collection(self, distance: str = "Cosine") -> None:
        logger.info("Creando colección Qdrant: %s (dim=%d)", self.collection, self.dim)
        params = qmodels.VectorParams(size=self.dim, distance=distance)
        try:
            self.client.recreate_collection(collection_name=self.collection, vectors_config=params)
        except Exception:
            # recreate_collection may fail if API differs; fallback to create
            try:
                self.client.create_collection(collection_name=self.collection, vectors_config=params)
            except Exception as e:
                logger.warning("No se pudo crear la colección: %s", e)

    def upsert(self, points: Iterable[Dict[str, Any]]) -> None:
        qpoints = []
        for p in points:
            qpoints.append(
                qmodels.PointStruct(id=p.get("id"), vector=p["vector"], payload=p.get("payload", {}))
            )

        logger.info("Upsert %d puntos en collection=%s", len(qpoints), self.collection)
        self.client.upsert(collection_name=self.collection, points=qpoints)

    def search(self, vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        hits = self.client.search(collection_name=self.collection, query_vector=vector, limit=top_k)
        results = []
        for h in hits:
            results.append({
                "id": h.id,
                "score": h.score,
                "payload": h.payload,
            })
        return results
