from pydantic import BaseModel, Field


class InvestigacionRequest(BaseModel):
    codsuc: str = Field(description="Código de sucursal")
    codcliente: str = Field(description="Código de cliente")
    codreclamo: str = Field(description="Código del reclamo")
    clasificacion: str = Field(description="Clasificación del reclamo")
    detalle: str = Field(description="Detalle del reclamo")
    anio: str = Field(default="2026", description="Año para record de facturación")
    modelo: str | None = None


class ProblemaNormadoSchema(BaseModel):
    tipo: str
    detalle: str
    articulos: list[dict] = Field(default_factory=list)
    accion: str | None = None
    responsable: str | None = None
    base_legal: str | None = None


class ResumenMedio(BaseModel):
    medio_id: str
    medio_nombre: str
    resumen: str
    datos: dict | None = None
    problemas: list[ProblemaNormadoSchema] = Field(default_factory=list)
    tiempo: float | None = None
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
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    clasificacion: str | None = Field(default=None, description="Clasificación del reclamo (contexto para la fundamentación)")
    modelo: str | None = None


class ProblemaInforme(BaseModel):
    medio_id: str
    tipo: str
    detalle: str
    accion: str | None = None
    responsable: str | None = None
    base_legal: str | None = None


class InformeResponse(BaseModel):
    codreclamo: str
    informe: str
    problemas: list[ProblemaInforme] = Field(default_factory=list)
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
    clasificacion: str = Field(description="Clasificación del reclamo")
    modelo: str | None = None


class InformeMetadata(BaseModel):
    numero: str
    fecha: str
    asunto: str
    reclamo: str
    suministro: str
    destinatario: str | None = None


class BuscarReclamoResponse(BaseModel):
    codreclamo: str
    datos: dict | None = None
    informe: InformeMetadata | None = None
    error: str | None = None
    tiempo: float
