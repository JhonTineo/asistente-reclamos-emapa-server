from abc import ABC, abstractmethod
from typing import Any, Optional

class PuertoEmapaAPI(ABC):
    """
    Puerto (Interfaz) para interactuar con la API del ERP de EMAPA.
    La capa de Aplicación usará esta interfaz para obtener datos del cliente.
    """

    @abstractmethod
    def set_token(self, token: Optional[str]) -> None:
        pass

    @abstractmethod
    def buscar_reclamo(self, codsede: str, codsuc: str, codreclamo: str, codcliente: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def obtener_saldo_actual(self, codsuc: str, codcliente: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def obtener_tarjeta_lectura(self, codsuc: str, codcliente: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def obtener_record_facturacion(self, codsuc: str, codcliente: str, anio: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def obtener_corte_reapertura(self, codsuc: str, codcliente: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def obtener_inspeccion_externa(self, codsuc: str, codinspeccion: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def obtener_inspeccion_interna(self, codsuc: str, codinspeccion: str) -> dict[str, Any]:
        pass
