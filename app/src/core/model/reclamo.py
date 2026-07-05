from pydantic import BaseModel, Field


class ClasificarReclamoRequest(BaseModel):
    suministro_id: str
    reclamo_id: str
    detalle: str
    modelo: str | None = None


class ClasificarReclamoResponse(BaseModel):
    reclamo_id: str
    suministro_id: str
    clasificacion: str = Field(description="Tipo de reclamo según Anexo 4")
    razonamiento: str = Field(description="Razonamiento del modelo para la clasificación")
