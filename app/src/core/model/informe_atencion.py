from dataclasses import dataclass
from datetime import datetime


@dataclass
class InformeAtencion:
    id: int
    numero: str
    fecha: datetime
    hallazgos: str
    conclusion: str