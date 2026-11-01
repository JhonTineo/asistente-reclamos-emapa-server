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

    def obtener_imagenes_cliente(self, codsuc: str, codcliente: str,
                                 fecha_inicial: str, fecha_final: str) -> dict[str, Any]:
        """Imágenes/archivos del cliente registrados en SYSCO entre dos fechas
        (YYYY-MM-DD): fotos de lectura, de inspección, formularios del reclamo.
        Cada ítem trae el contenido en base64 (`img64`). No es abstracto para
        no obligar a otras implementaciones del puerto a soportarlo."""
        raise NotImplementedError
