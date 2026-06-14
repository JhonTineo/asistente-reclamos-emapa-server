from pydantic import BaseModel, Field


class InvestigacionRequest(BaseModel):
    codsuc: str = Field(description="Código de sucursal")
    codcliente: str = Field(description="Código de cliente")
    codreclamo: str = Field(description="Código del reclamo")
    clasificacion: str = Field(description="Clasificación del reclamo")
    detalle: str = Field(description="Detalle del reclamo")
    anio: str = Field(default="2026", description="Año para record de facturación")
    modelo: str | None = None


class ResumenMedio(BaseModel):
    medio_id: str
    medio_nombre: str
    resumen: str
    estado: str = "ok"
    error: str | None = None


class InvestigacionResponse(BaseModel):
    codreclamo: str
    codsuc: str
    codcliente: str
    clasificacion: str
    detalle: str
    resumenes: list[ResumenMedio]
    tiempo_total: float


class InformeRequest(BaseModel):
    codsuc: str = Field(description="Código de sucursal")
    codcliente: str = Field(description="Código de cliente")
    codreclamo: str = Field(description="Código del reclamo")
    clasificacion: str = Field(description="Clasificación del reclamo")
    detalle: str = Field(description="Detalle del reclamo")
    resumenes: list[ResumenMedio] = Field(description="Resúmenes verificados por el usuario")
    modelo: str | None = None


class InformeResponse(BaseModel):
    codreclamo: str
    informe: str
    tiempo: float
