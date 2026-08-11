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
    seleccionado: bool = False
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


class ArticuloSeleccion(BaseModel):
    """Artículo curado por el usuario para un problema (o recuperado por RAG)."""
    article: str | None = None
    numeral: str | None = None
    texto: str | None = None
    score: float | None = None
    aplica: bool = True
    manual: bool = False


class ProblemaSeleccion(BaseModel):
    """Un problema marcado como determinante por el usuario. `articulos=None`
    significa que el backend debe recuperarlos por RAG (problema recién marcado);
    una lista (aunque vacía) significa que ya vienen curados y se usan tal cual."""
    medio_id: str
    detalle: str
    articulos: list[ArticuloSeleccion] | None = None


class InformeRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    clasificacion: str | None = Field(default=None, description="Clasificación del reclamo (contexto para la fundamentación)")
    modelo: str | None = None
    # Selección MANUAL de problemas determinantes desde el front. Si viene, la
    # fundamentación NO usa el selector por LLM: usa exactamente estos problemas
    # (y sus artículos curados, si los trae). Si es None, es el pase automático.
    seleccion: list[ProblemaSeleccion] | None = None


class ProblemaInforme(BaseModel):
    medio_id: str
    tipo: str
    detalle: str
    seleccionado: bool = False
    articulos: list[dict] = Field(default_factory=list)
    accion: str | None = None
    responsable: str | None = None
    base_legal: str | None = None


class InformeResponse(BaseModel):
    codreclamo: str
    # Opcionales porque /investigacion/fundamentar-normativa no arma el texto
    # del informe: devuelve el detalle estructurado (suministro, clasificación,
    # objetivos) para que el frontend lo renderice. Los demás endpoints que
    # usan este response_model sí mandan `informe` y omiten esos campos.
    informe: str = ""
    suministro: str | None = None
    clasificacion: str | None = None
    objetivos: list["ObjetivoInvestigacionSchema"] = Field(default_factory=list)
    problemas: list[ProblemaInforme] = Field(default_factory=list)
    # Párrafo de fundamentación normativa (nuevo flujo /fundamentar-normativa):
    # se genera de los hallazgos determinantes y se renderiza antes de la conclusión.
    fundamentacion: str | None = None
    tiempo: float


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
    # Opcional: si no viene, se usa informe.propuesta_conciliacion ya guardado
    # en el store (la generada por POST /conciliacion/propuesta, o la editada
    # a mano por PATCH /conciliacion/propuesta). El caso normal solo manda codreclamo.
    propuesta_conciliacion: str | None = Field(
        default=None,
        description="Propuesta de conciliación de la empresa (opcional; por defecto se usa la ya guardada en el informe)",
    )
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


class IniciarInvestigacionRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    codcliente: str = Field(description="Código de cliente / suministro")
    datos: dict = Field(
        description=(
            "Detalle CRUDO del reclamo tal como lo devuelve EMAPA en "
            "reclamo/obtener/detalle/... (incluida su clave 'data'), ya obtenido "
            "por el frontend en la pantalla de detalle. Evita una segunda "
            "consulta a EMAPA para el mismo reclamo."
        )
    )
    sesion_id: str | None = Field(
        default=None,
        description=(
            "Identificador de la pestaña/sesión del frontend. Si otra sesión ya "
            "está atendiendo este reclamo, se rechaza con 409."
        ),
    )
    creado_por: str | None = Field(
        default=None,
        description="Usuario que inició la atención, para organizar la cola.",
    )


class ReclamoSchema(BaseModel):
    codcliente: str | None = None
    reclamante: str | None = None
    propietario: str | None = None
    dni: str | None = None
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


class IniciarInvestigacionResponse(BaseModel):
    # A diferencia de BuscarReclamoResponse, NO devuelve `datos` (el detalle
    # crudo del reclamo): el frontend ya lo tiene (fue quien lo mandó), así que
    # reenviarlo sería redundante. Solo interesa el informe de atención creado.
    codreclamo: str
    informe: InformeMetadata | None = None
    error: str | None = None
    tiempo: float


# --- Objetivos de investigación (se generan tras buscar el reclamo) ---
class ObjetivoInvestigacionSchema(BaseModel):
    id: int
    descripcion: str
    medio: str | None = None
    determinante: bool = False


# InformeResponse se define más arriba y referencia ObjetivoInvestigacionSchema
# como forward ref; hay que resolverla ahora que la clase ya existe.
InformeResponse.model_rebuild()


class ObjetivosRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    modelo: str | None = None


class ObjetivosResponse(BaseModel):
    codreclamo: str
    objetivos: list[ObjetivoInvestigacionSchema] = Field(default_factory=list)
    tiempo: float


# --- Disponibilidad de medios probatorios (chequeo rápido sin LLM) ---
class MedioDisponible(BaseModel):
    medio_id: str
    disponible: bool
    error: str | None = None


# El orquestador completo (búsqueda + objetivos + medios + conclusión) vive
# ahora en reclamos.py con sus propios request/response (InformeAutomaticoRequest/
# Response), definidos ahí porque son específicos de ese endpoint.


# --- Edición manual de textos ya generados (sin invocar al LLM) ---
class ActualizarResumenRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    resumen: str = Field(description="Nuevo texto del resumen (edición manual)")


class ActualizarResumenResponse(BaseModel):
    codreclamo: str
    medio_id: str
    resumen: str
    informe_texto: str


class ActualizarConclusionRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    conclusion: str = Field(description="Nuevo texto de la conclusión (edición manual)")


class ActualizarConclusionResponse(BaseModel):
    codreclamo: str
    conclusion: str
    informe_texto: str


class ActualizarFundamentacionRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    fundamentacion: str = Field(description="Nuevo texto del párrafo de fundamentación normativa (edición manual)")


class ActualizarFundamentacionResponse(BaseModel):
    codreclamo: str
    fundamentacion: str
    informe_texto: str


# --- Informe de Sustentación del Régimen de Facturación (documento aparte) ---
class CategoriaUsoSchema(BaseModel):
    codigo: str
    nombre: str
    unidades: int | None = None
    es_cliente: bool = False


class LecturaHitoSchema(BaseModel):
    fecha: str | None = None
    lectura: float | None = None
    observacion: str | None = None


class FilaHistoricoSchema(BaseModel):
    mes_anio: str | None = None
    modalidad: str | None = None
    volumen: float | None = None
    marca: str | None = None


class ClientePredioSchema(BaseModel):
    suministro: str | None = None
    nombre_usuario: str | None = None
    dni: str | None = None
    direccion: str | None = None
    mes_facturacion: str | None = None
    categorias: list[CategoriaUsoSchema] = Field(default_factory=list)


class FacturacionEvaluadaSchema(BaseModel):
    modalidad: str | None = None
    volumen_facturado: float | None = None
    lectura_anterior: LecturaHitoSchema = Field(default_factory=LecturaHitoSchema)
    lectura_actual: LecturaHitoSchema = Field(default_factory=LecturaHitoSchema)


class ValoresCalculadosSchema(BaseModel):
    dif_lecturas: float | None = None
    promedio_historico: float | None = None
    consumo_asignado: float | None = None
    meses_promedio: str | None = None
    observacion_consumo: str | None = None


class FichaMedidorSchema(BaseModel):
    nro_serie: str | None = None
    estado: str | None = None
    marca: str | None = None
    modelo: str | None = None
    diametro: str | None = None
    modelo_homologacion: str | None = None
    nro_certificado: str | None = None
    fecha_instalacion: str | None = None
    fecha_verificacion: str | None = None
    tipo_verificacion: str | None = None
    solicitante: str | None = None
    uvm: str | None = None


class ConexionSchema(BaseModel):
    fecha_nacimiento: str | None = None
    fecha_instalacion_medidor: str | None = None
    nro_acta: str | None = None


class SustentacionResponse(BaseModel):
    codreclamo: str
    cliente: ClientePredioSchema = Field(default_factory=ClientePredioSchema)
    facturacion: FacturacionEvaluadaSchema = Field(default_factory=FacturacionEvaluadaSchema)
    valores: ValoresCalculadosSchema = Field(default_factory=ValoresCalculadosSchema)
    historico: list[FilaHistoricoSchema] = Field(default_factory=list)
    medidor: FichaMedidorSchema = Field(default_factory=FichaMedidorSchema)
    conexion: ConexionSchema = Field(default_factory=ConexionSchema)


class ActualizarPropuestaRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    propuesta: str = Field(description="Nuevo texto de la propuesta de conciliación (edición manual)")


class ActualizarPropuestaResponse(BaseModel):
    codreclamo: str
    propuesta: str


# --- Edición manual de los demás datos de la conciliación (no la propuesta de
# la empresa, que ya tiene su propio PATCH /conciliacion/propuesta arriba) ---
class GuardarConciliacionRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo")
    propuesta_empresa: str | None = Field(default=None, description="Propuesta de la EPS")
    propuesta_reclamante: str | None = Field(default=None, description="Postura del cliente")
    puntos_acuerdo: str | None = Field(default=None, description="Puntos de acuerdo")
    puntos_desacuerdo: str | None = Field(default=None, description="Puntos de desacuerdo")
    observaciones: str | None = Field(default=None, description="Observaciones adicionales")


class ActualizarConciliacionRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    propuesta_reclamante: str | None = Field(default=None, description="Postura/propuesta del cliente frente a la conciliación")
    puntos_acuerdo: str | None = Field(default=None, description="Puntos en los que llegaron a un acuerdo")
    puntos_desacuerdo: str | None = Field(default=None, description="Puntos en los que no llegaron a un acuerdo")
    observaciones: str | None = Field(default=None, description="Observaciones del reclamante o de la EPS")


class ActualizarConciliacionResponse(BaseModel):
    codreclamo: str
    propuesta_reclamante: str
    puntos_acuerdo: str
    puntos_desacuerdo: str
    observaciones: str


class ActualizarResolucionTextoRequest(BaseModel):
    codreclamo: str = Field(description="Código del reclamo (clave del informe en el store)")
    resolucion: str = Field(description="Nuevo texto de la resolución (edición manual)")


class ActualizarResolucionTextoResponse(BaseModel):
    codreclamo: str
    resolucion: str


# --- Recuperación del informe completo (rehidratación tras recargar la página) ---
class InformeCompletoResponse(BaseModel):
    codreclamo: str
    informe: InformeMetadata
    objetivos: list[ObjetivoInvestigacionSchema] = Field(default_factory=list)
    resumenes: list[ResumenMedio] = Field(default_factory=list)
    ventana_meses: list[tuple[int, int]] = Field(default_factory=list)
    fundamentacion: str | None = None
    veredicto: str | None = None
    conclusion: str | None = None
    problemas: list[ProblemaInforme] = Field(default_factory=list)
    propuesta_conciliacion: str | None = None
    resolucion: str | None = None
    informe_texto: str = ""
