"""Puerto de persistencia de la memoria del caso (InformeAtencion)."""

from typing import Protocol

from app.src.core.model.informe_atencion import InformeAtencion


class PuertoRepositorioCasos(Protocol):

    def guardar(self, informe: InformeAtencion) -> None:
        """Sincroniza el estado completo del informe en curso. Debe ser
        idempotente: guardar dos veces el mismo estado no crea versiones."""
        ...

    def cargar_abiertos(self) -> list[InformeAtencion]:
        """Informes cuya atención sigue abierta (para reconstruir la memoria
        del servidor al arrancar)."""
        ...

    def cerrar(self, codreclamo: str, descartar: bool = False) -> None:
        """Cierra la atención abierta del reclamo. ``descartar=True`` la borra
        por completo (inicio fallido); si no, se conserva como finalizada."""
        ...
