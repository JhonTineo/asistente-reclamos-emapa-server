from dataclasses import dataclass
from datetime import datetime


@dataclass
class Resolucion:
    id: int
    numero: str
    fecha: datetime
    decision: str
    fundamento: str