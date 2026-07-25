from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class MensajeLLM:
    rol: str       # "system", "user", "assistant"
    contenido: str


class PuertoProveedorLLM(ABC):
    """Puerto para interactuar con proveedores de inferencia LLM (OpenAI, OpenRouter, Ollama)."""

    @abstractmethod
    def generar_texto(self, mensajes: list[MensajeLLM], modelo_id: str, temperatura: float = 0.0) -> str:
        """Genera una respuesta en texto plano dada una lista de mensajes."""
        pass

    @abstractmethod
    def generar_json(self, mensajes: list[MensajeLLM], modelo_id: str, esquema: dict[str, Any] | None = None, temperatura: float = 0.0) -> str:
        """Genera una respuesta garantizada en formato JSON, idealmente forzando el
        esquema proporcionado (Structured Outputs) si el proveedor lo soporta."""
        pass
