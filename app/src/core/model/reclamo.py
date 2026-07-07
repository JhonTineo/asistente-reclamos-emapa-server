from dataclasses import dataclass
from datetime import datetime


@dataclass
class Reclamo:
    id: int
    codigo: str
    tipo: str
    descripcion: str
    fecha_creacion: datetime
    estado: str