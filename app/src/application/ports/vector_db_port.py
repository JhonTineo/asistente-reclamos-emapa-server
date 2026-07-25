from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class PuertoBaseVectorial(ABC):
    """
    Puerto (Interfaz) para interactuar con una base de datos vectorial.
    La capa de Aplicación usará esta interfaz sin saber qué base de datos real se usa.
    """

    @abstractmethod
    def create_collection(self, collection_name: Optional[str] = None, dimension: int = 768) -> None:
        pass

    @abstractmethod
    def collection_exists(self, collection_name: str) -> bool:
        pass

    @abstractmethod
    def get_collections(self) -> List[str]:
        pass

    @abstractmethod
    def upsert(self, points: List[Dict[str, Any]], collection_name: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def search(self, vector: List[float], top_k: int = 5, collection_name: Optional[str] = None) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def count(self) -> int:
        pass

    @abstractmethod
    def delete(self, point_id: str, collection_name: Optional[str] = None) -> None:
        pass

    @abstractmethod
    def get_all(self, collection_name: Optional[str] = None) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def search_by_keyword(self, keyword: str, collection_name: Optional[str] = None, top_k: int = 15) -> List[Dict[str, Any]]:
        pass
