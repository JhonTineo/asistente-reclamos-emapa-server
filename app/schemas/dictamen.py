from pydantic import BaseModel
from typing import List


class Dictamen(BaseModel):

    clasificacion: str

    procede: bool

    nivel_confianza: float

    articulos_aplicables: List[str]

    fundamento: str

    requiere_revision_humana: bool