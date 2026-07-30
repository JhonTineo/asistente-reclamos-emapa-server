import os
import logging
import unicodedata
from typing import List, Dict, Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from qdrant_client.http.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

from app.src.application.ports.vector_db_port import PuertoBaseVectorial
from app.src.application.services.rag.legal_chunker import normalizar_numero_articulo

logger = logging.getLogger(__name__)

class QdrantAdapter(PuertoBaseVectorial):
    """
    Adaptador de Infraestructura para Qdrant.
    Unifica la lógica antigua de QdrantStore y vector_db bajo el nuevo Puerto.
    """

    def __init__(self, client: QdrantClient = None, collection_name: str = None, dim: int = 768):
        self.collection_name = (
            collection_name
            or os.getenv("QDRANT_COLLECTION_NAME", "sunass_reglamento")
        )
        self.dim = dim
        
        if client is not None:
            self.client = client
        else:
            self.client = QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))

    def create_collection(self, collection_name: Optional[str] = None, dimension: int = 768) -> None:
        target = collection_name or self.collection_name
        if self.collection_exists(target):
            return
            
        self.client.create_collection(
            collection_name=target,
            vectors_config=VectorParams(
                size=dimension,
                distance=Distance.COSINE
            )
        )
        logger.info(f"Colección Qdrant creada: {target}")

    def delete_collection(self, collection_name: Optional[str] = None) -> None:
        target = collection_name or self.collection_name
        if self.collection_exists(target):
            self.client.delete_collection(collection_name=target)
            logger.info(f"Colección Qdrant eliminada: {target}")

    def collection_exists(self, collection_name: str) -> bool:
        try:
            collections = self.client.get_collections()
            return collection_name in [c.name for c in collections.collections]
        except Exception:
            return False

    def get_collections(self) -> List[str]:
        try:
            collections = self.client.get_collections()
            return [c.name for c in collections.collections]
        except Exception:
            return []

    def upsert(self, points: List[Dict[str, Any]], collection_name: Optional[str] = None) -> None:
        target = collection_name or self.collection_name
        qdrant_points = []
        for p in points:
            qdrant_points.append(
                PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p.get("payload", {})
                )
            )

        self.client.upsert(
            collection_name=target,
            points=qdrant_points
        )

    def search(self, vector: List[float], top_k: int = 5, collection_name: Optional[str] = None) -> List[Dict[str, Any]]:
        target = collection_name or self.collection_name
        query_filter = Filter(
            must_not=[
                FieldCondition(
                    key="estado",
                    match=MatchValue(value="inactivo")
                )
            ]
        )
        
        # En qdrant-client >= 1.15 se recomienda usar query_points
        results = self.client.query_points(
            collection_name=target,
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
        
    def count(self) -> int:
        return self.client.count(collection_name=self.collection_name).count
        
    def delete(self, point_id: str, collection_name: Optional[str] = None) -> None:
        target = collection_name or self.collection_name
        self.client.set_payload(
            collection_name=target,
            payload={"estado": "inactivo"},
            points=[point_id]
        )

    def get_by_article(self, article: str, collection_name: Optional[str] = None, incluir_inactivos: bool = True) -> List[Dict[str, Any]]:
        """Devuelve todos los puntos (numerales) de un mismo artículo.

        Compara por número de artículo normalizado, de modo que '62-A', '62 - A'
        y 'ARTÍCULO 62-A' se resuelven al mismo artículo.
        """
        art_norm = normalizar_numero_articulo(article)
        encontrados = []
        for p in self.get_all(collection_name=collection_name):
            payload = p.get("payload") or {}
            if not incluir_inactivos and payload.get("estado") == "inactivo":
                continue
            if normalizar_numero_articulo(payload.get("article", "")) == art_norm:
                encontrados.append(p)
        return encontrados

    def deactivate_article(self, article: str, collection_name: Optional[str] = None) -> List[str]:
        """Desactiva (soft-delete) TODOS los numerales de un artículo.

        Se usa antes de reinsertar la versión modificada de un artículo, para
        que no queden numerales viejos conviviendo con los nuevos.
        Devuelve los IDs desactivados.
        """
        target = collection_name or self.collection_name
        ids = [
            p["id"]
            for p in self.get_by_article(article, collection_name=target)
            if (p.get("payload") or {}).get("estado") != "inactivo"
        ]
        if ids:
            self.client.set_payload(
                collection_name=target,
                payload={"estado": "inactivo"},
                points=ids,
            )
        return ids

    def get_all(self, collection_name: Optional[str] = None) -> List[Dict[str, Any]]:
        target = collection_name or self.collection_name
        points = []
        try:
            offset = None
            while True:
                results, next_offset = self.client.scroll(
                    collection_name=target,
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

    def search_by_keyword(self, keyword: str, collection_name: Optional[str] = None, top_k: int = 15) -> List[Dict[str, Any]]:
        target = collection_name or self.collection_name

        def _normalize(s: str) -> str:
            if not s:
                return ""
            s = unicodedata.normalize('NFKD', str(s))
            return "".join(c for c in s if not unicodedata.combining(c)).lower()

        norm_keyword = _normalize(keyword)
        exact_matches = []
        try:
            offset = None
            while True:
                results, next_offset = self.client.scroll(
                    collection_name=target,
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
            
        return exact_matches[:top_k]
