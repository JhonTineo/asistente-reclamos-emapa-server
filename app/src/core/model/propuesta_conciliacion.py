from dataclasses import dataclass
from datetime import datetime


@dataclass
class PropuestaConciliacion:
    id: int
    fecha: datetime
    propuesta: str
    fundamento: str