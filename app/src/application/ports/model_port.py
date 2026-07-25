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

    @abstractmethod
    def modelos_para_proveedor(self, proveedor_id: str) -> list[str]:
        """Modelos configurados para un proveedor, en orden de preferencia
        (el primero es el que ese proveedor debe usar por defecto). La usa el
        router en modo AUTO: al no haber un modelo_id explícito, prueba cada
        proveedor del combo con SU mejor modelo en vez de un id fijo, que es
        lo que permite cruzar proveedores con nomenclaturas de modelo distintas
        (ej. "openai/gpt-4o-mini" en OpenRouter vs "llama-3.3-70b-versatile"
        en Groq)."""
        pass
