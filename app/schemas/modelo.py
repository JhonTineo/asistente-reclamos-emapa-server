from pydantic import BaseModel


class ModeloResponse(BaseModel):
    id: str


class ModelosListResponse(BaseModel):
    modelos: list[ModeloResponse]
