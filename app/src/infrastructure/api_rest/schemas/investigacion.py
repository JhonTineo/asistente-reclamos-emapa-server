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


class InformePreviewRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")


class InformePreviewResponse(BaseModel):
    codreclamo: str
    informe: str


class ConciliacionRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    # Campos legados que el frontend aún puede enviar; ya no se usan: la propuesta
    # se arma desde la conclusión del informe guardado en el store.
    codsuc: str | None = None
    codcliente: str | None = None
    clasificacion: str | None = None
    informe_atencion: str | None = None
    modelo: str | None = None


class ConciliacionResponse(BaseModel):
    codreclamo: str
    propuesta: str
    tiempo: float


class ResolucionRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    propuesta_conciliacion: str = Field(description="Propuesta de conciliación de la empresa")
    propuesta_reclamante: str | None = Field(default=None, description="Postura/propuesta del cliente frente a la conciliación")
    observaciones: str | None = Field(default=None, description="Observaciones adicionales")
    modelo: str | None = None
    # Campos legados que el frontend aún puede enviar; ya no se usan: el
    # reclamo y la conclusión se leen del informe guardado en el store.
    codsuc: str | None = None
    codcliente: str | None = None
    informe_atencion: str | None = None


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
    meses: int = Field(default=12, description="Ventana de meses a analizar")
    modelo: str | None = None


class ReclamoSchema(BaseModel):
    codcliente: str | None = None
    reclamante: str | None = None
    propietario: str | None = None
    tipo_reclamo: str | None = None
    clasificacion_reclamo: str | None = None
    motivo_reclamo: str | None = None
    meses_reclamados: str | None = None
    fecha_recepcion: str | None = None
    estado_reclamo: str | None = None


class InformeMetadata(BaseModel):
    numero: str
    fecha: str
    asunto: str
    reclamo: str
    suministro: str
    destinatario: str | None = None
    datos_reclamo: ReclamoSchema | None = None


class BuscarReclamoResponse(BaseModel):
    codreclamo: str
    datos: dict | None = None
    informe: InformeMetadata | None = None
    error: str | None = None
    tiempo: float


# --- Objetivos de investigación (se generan tras buscar el reclamo) ---
class ObjetivoInvestigacionSchema(BaseModel):
    id: int
    descripcion: str
    medio: str | None = None
    determinante: bool = False


class ObjetivosRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    modelo: str | None = None


class ObjetivosResponse(BaseModel):
    codreclamo: str
    objetivos: list[ObjetivoInvestigacionSchema] = Field(default_factory=list)
    tiempo: float


# --- Disponibilidad de medios probatorios (chequeo rápido sin LLM) ---
class MediosDisponiblesRequest(BaseModel):
    codsuc: str = Field(description="Código de sucursal")
    codcliente: str = Field(description="Código de cliente")
    codreclamo: str = Field(description="Código del reclamo (para reutilizar el token guardado)")
    anio: str = Field(default="2026", description="Año para el record de facturación")


class MedioDisponible(BaseModel):
    medio_id: str
    disponible: bool
    error: str | None = None


class MediosDisponiblesResponse(BaseModel):
    codreclamo: str
    medios: list[MedioDisponible] = Field(default_factory=list)
    tiempo: float


# --- Recuperación del informe completo (rehidratación tras recargar la página) ---
class InformeCompletoResponse(BaseModel):
    codreclamo: str
    informe: InformeMetadata
    objetivos: list[ObjetivoInvestigacionSchema] = Field(default_factory=list)
    resumenes: list[ResumenMedio] = Field(default_factory=list)
    ventana_meses: list[tuple[int, int]] = Field(default_factory=list)
    veredicto: str | None = None
    conclusion: str | None = None
    problemas: list[ProblemaInforme] = Field(default_factory=list)
    propuesta_conciliacion: str | None = None
    resolucion: str | None = None
    informe_texto: str = ""
