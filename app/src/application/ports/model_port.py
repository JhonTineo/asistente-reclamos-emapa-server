from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModeloInfo:
    """Representa las características de un Modelo LLM en el sistema,
    independientemente de qué proveedor lo sirva."""
    id: str             # Ej: "gpt-4o-mini", "llama-3"
    label: str          # Ej: "GPT 4o Mini", "Llama 3 (Local)"
    context_window: int = 128000
    is_local: bool = False


class PuertoCatalogoModelos(ABC):
    """Puerto para interactuar con el catálogo de modelos disponibles."""

    @abstractmethod
    def listar_modelos(self) -> list[ModeloInfo]:
        """Devuelve todos los modelos registrados en el catálogo."""
        pass

    @abstractmethod
    def obtener_modelo(self, modelo_id: str) -> Optional[ModeloInfo]:
        """Devuelve la información de un modelo específico."""
        pass

    @abstractmethod
    def proveedores_para(self, modelo_id: str) -> list[str]:
        """Devuelve una lista ordenada de los IDs de los proveedores
        que pueden servir este modelo. El primero es el preferido, los
        siguientes son fallbacks."""
        pass
