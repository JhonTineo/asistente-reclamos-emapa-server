from pydantic import BaseModel, Field


class TareaInforme(BaseModel):
    id: str = Field(description="ID único de la tarea (ej: inf-1)")
    nombre: str = Field(description="Nombre del informe a generar")
    medios_requeridos: list[str] = Field(description="Lista de medios probatorios necesarios")
    prompt: str = Field(description="Prompt del sistema para el agente que ejecutará esta tarea")
    entrada: dict = Field(description="Parámetros de entrada para la tarea")
    salida: str = Field(description="Descripción del resultado esperado")


class Hallazgo(BaseModel):
    informe_id: str = Field(description="ID del informe que generó este hallazgo")
    informe_nombre: str = Field(description="Nombre del informe")
    medios_utilizados: list[str] = Field(description="Medios probatorios que fueron analizados")
    hallazgos: list[str] = Field(description="Lista de hallazgos encontrados")
    conclusion: str = Field(description="Conclusión del análisis de este informe")


class PlanificarInvestigacionRequest(BaseModel):
    suministro_id: str | None = Field(default=None, description="ID del suministro (opcional, usa reclamo_id si no se provee)")
    reclamo_id: str
    clasificacion: str = Field(description="Clasificación del reclamo según Anexo 1")
    detalle: str = Field(description="Detalle original del reclamo")
    modelo: str | None = None


class PlanificarInvestigacionResponse(BaseModel):
    reclamo_id: str
    clasificacion: str
    descripcion_planificacion: str = Field(description="Descripción breve del plan de investigación")
    tareas: list[TareaInforme]


class EjecutarInvestigacionRequest(BaseModel):
    reclamo_id: str
    clasificacion: str
    detalle: str
    descripcion_planificacion: str = Field(description="Descripción del plan de investigación")
    tareas: list[TareaInforme]
    modelo: str | None = None


class ResultadoInvestigacion(BaseModel):
    reclamo_id: str
    clasificacion: str
    descripcion_planificacion: str
    resultados_tareas: list[Hallazgo]
    explicacion_unificada: str = Field(description="Explicación unificada del problema que generó el reclamo")


class InvestigacionRequest(BaseModel):
    suministro_id: str = Field(description="ID del suministro")
    codsede: str | None = Field(default=None, description="Código de sede EMAPA")
    codsuc: str | None = Field(default=None, description="Código de sucursal EMAPA")
    codcliente: str | None = Field(default=None, description="Código de cliente EMAPA")
    codreclamo: str | None = Field(default=None, description="Código de reclamo EMAPA")
    anio: str | None = Field(default=None, description="Año de consulta para facturación")
    detalle_reclamo: str = Field(description="Detalle del reclamo")
    modelo: str | None = None


class ResultadoInvestigacionCompleto(BaseModel):
    reclamo_id: str
    suministro_id: str
    clasificacion: str
    descripcion_plan: str = Field(description="Descripción del plan de investigación")
    tareas: list[TareaInforme]
    resultados_tareas: list[Hallazgo]
    explicacion_unificada: str
    procede: str = Field(description="si | no | parcialmente")
    acciones: list[str]