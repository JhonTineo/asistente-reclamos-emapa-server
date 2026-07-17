from pydantic import BaseModel, Field


class ModeloResponse(BaseModel):
    id: str


class ModelosListResponse(BaseModel):
    modelos: list[ModeloResponse]


class ModelosCargadosResponse(BaseModel):
    modelos: list[str] = Field(default_factory=list, description="Modelos actualmente en memoria")


class ModeloAccionRequest(BaseModel):
    modelo: str = Field(description="Nombre del modelo (tal como lo devuelve /modelos)")


class ModeloAccionResponse(BaseModel):
    modelo: str
    ok: bool
    en_memoria: bool
    tiempo: float
    error: str | None = None
