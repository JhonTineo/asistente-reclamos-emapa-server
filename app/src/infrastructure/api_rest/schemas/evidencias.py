from pydantic import BaseModel


class MesConsumo(BaseModel):
    anio: int
    mes: int
    etiqueta: str
    etiqueta_corta: str
    consumo: float | None = None
    consumo_medido: float | None = None
    consumo_facturado: float | None = None
    importe: float | None = None
    forma_facturacion: str | None = None
    lectura_anterior: float | None = None
    lectura_actual: float | None = None
    fecha_lectura: str | None = None
    estado_lectura: str | None = None
    refacturado: bool = False
    reclamado: bool = False


class IndicadoresConsumo(BaseModel):
    periodo: str
    anio: int
    mes: int
    consumo_reclamado: float | None = None
    consumo_medido: float | None = None
    importe_reclamado: float | None = None
    lectura_anterior: float | None = None
    lectura_actual: float | None = None
    fecha_lectura: str | None = None
    forma_facturacion: str | None = None
    promedio_previo: float | None = None
    meses_base: int = 0
    periodo_base: str | None = None
    minimo_previo: float | None = None
    maximo_previo: float | None = None
    veces_promedio: float | None = None
    variacion_pct: float | None = None
    nivel: str
    interpretacion: str


class PuntoInspeccion(BaseModel):
    punto: str
    resultado: str
    estado: str          # "conforme" | "alerta"


class PuntoAgua(BaseModel):
    tipo: str
    cantidad: int


class InspeccionExternaEvidencia(BaseModel):
    nroinspeccion: str | None = None
    fecha: str | None = None
    puntos: list[PuntoInspeccion] = []
    observaciones: list[str] = []
    alertas: int = 0


class InspeccionInternaEvidencia(BaseModel):
    nroinspeccion: str | None = None
    fecha: str | None = None
    puntos: list[PuntoInspeccion] = []
    puntos_agua: list[PuntoAgua] = []
    total_puntos_agua: int = 0
    unidades_uso: int = 0
    observaciones: list[str] = []
    alertas: int = 0


class Hito(BaseModel):
    fecha: str
    texto: str
    tipo: str


class Verificacion(BaseModel):
    id: int
    descripcion: str
    medio: str | None = None
    seccion: str
    resultado: str | None = None
    evidencia: str | None = None


class DisponibilidadEvidencias(BaseModel):
    consumo: bool = False
    inspeccion_externa: bool = False
    inspeccion_interna: bool = False


class EvidenciasResponse(BaseModel):
    codreclamo: str
    suministro: str | None = None
    clasificacion: str | None = None
    tipo_reclamo: str | None = None
    meses_reclamados: str | None = None
    periodos_reclamados: list[str] = []
    fecha_recepcion: str | None = None
    veredicto: str | None = None
    verificaciones: list[Verificacion] = []
    serie: list[MesConsumo] = []
    indicadores: IndicadoresConsumo | None = None
    inspeccion_externa: InspeccionExternaEvidencia | None = None
    inspeccion_interna: InspeccionInternaEvidencia | None = None
    linea_tiempo: list[Hito] = []
    disponible: DisponibilidadEvidencias
    generado: str


class FotoEvidencia(BaseModel):
    id: str
    categoria: str       # "lectura" | "inspeccion" | "formulario" | "otra"
    titulo: str
    fecha: str | None = None
    periodo: str | None = None
    nombre: str | None = None
    mime: str
    ancho: int | None = None
    alto: int | None = None
    kb: int
    base64: str


class ConsultaFotos(BaseModel):
    desde: str
    hasta: str
    archivos: int


class FotosEvidenciaResponse(BaseModel):
    codreclamo: str
    fotos: list[FotoEvidencia] = []
    consultas: list[ConsultaFotos] = []
    omitidas: dict[str, int] = {}
    resumen: dict[str, int] = {}
    tiempo_s: float = 0
    obtenido: str
    desde_cache: bool = False
