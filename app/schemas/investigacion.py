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


class ConciliacionRequest(BaseModel):
    codsuc: str = Field(description="Código de sucursal")
    codcliente: str = Field(description="Código de cliente")
    codreclamo: str = Field(description="Código del reclamo")
    clasificacion: str = Field(description="Clasificación del reclamo")
    informe_atencion: str = Field(description="Informe de atención generado en la investigación")
    modelo: str | None = None


class ConciliacionResponse(BaseModel):
    codreclamo: str
    propuesta: str
    tiempo: float


class ResolucionRequest(BaseModel):
    codsuc: str = Field(description="Código de sucursal")
    codcliente: str = Field(description="Código de cliente")
    codreclamo: str = Field(description="Código del reclamo")
    informe_atencion: str = Field(description="Informe de atención de la investigación")
    propuesta_conciliacion: str = Field(description="Propuesta de conciliación")
    observaciones: str | None = Field(default=None, description="Observaciones adicionales")
    modelo: str | None = None


class ResolucionResponse(BaseModel):
    codreclamo: str
    tipo: str = Field(description="FUNDADO o INFUNDADO")
    resolucion: str
    tiempo: float


class BuscarReclamoRequest(BaseModel):
    codsuc: str = Field(description="Código de sucursal")
    codreclamo: str = Field(description="Código del reclamo")
    codcliente: str = Field(description="Código de cliente")


class BuscarReclamoResponse(BaseModel):
    codreclamo: str
    datos: dict | None = None
    error: str | None = None
    tiempo: float
