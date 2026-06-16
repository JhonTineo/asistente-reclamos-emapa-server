import os
import time
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
        
        # Intento con reintentos para manejar timeouts en recreate_collection
        max_retries = 5
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    self.client.recreate_collection(collection_name=self.collection, vectors_config=params)
                else:
                    # Si recrear falla porque la colección existe o está siendo usada, intentar crear directamente
                    time.sleep(2 ** attempt * 0.5)  # backoff exponencial con sleep corto (ms)
                    self.client.recreate_collection(collection_name=self.collection, vectors_config=params)
                logger.info("Colección creada correctamente")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    remaining = max_retries - 1 - attempt
                    wait_time = min(2 ** (attempt + 1), 5) / 1000.0  # sleep en milisegundos corto
                    logger.warning(f"recreate_collection falló intentando {attempt+1}/{max_retries}: %s", e)
                else:
                    try:
                        self.client.create_collection(collection_name=self.collection, vectors_config=params)
                        logger.info("Colección creada con create_collection")
                        return
                    except Exception as fallback_e:
                        logger.warning(f"No se pudo crear la colección después de {max_retries} intentos: %s", str(e)[:100])

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
