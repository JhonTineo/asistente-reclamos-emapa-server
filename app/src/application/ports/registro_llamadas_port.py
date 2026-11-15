"""Puerto para registrar cada llamada al LLM (qué contexto vio y qué respondió)."""

from typing import Protocol


class PuertoRegistroLlamadas(Protocol):

    def registrar_llamada(
        self,
        *,
        codreclamo: str | None,
        paso: str,
        skill: str | None,
        skill_version: str | None,
        modelo: str | None,
        capas: dict,
        system: str,
        usuario: str,
        respuesta: str | None,
        duracion_ms: int,
        error: str | None,
        proveedor: str | None = None,
    ) -> None:
        ...
