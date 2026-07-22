from dataclasses import dataclass, field


@dataclass
class CategoriaUso:
    """Una columna de la matriz CATEGORÍA / UNIDADES DE USO del encabezado."""
    codigo: str                          # "DOM" | "DOM 2" | "COM" | "IND" | "EST" | "SOC"
    nombre: str
    unidades: int | None = None          # EMAPA no expone el conteo; solo se marca la del cliente
    es_cliente: bool = False             # True en la categoría a la que pertenece el suministro


@dataclass
class LecturaHito:
    """Una toma de lectura puntual (anterior o actual) del mes reclamado."""
    fecha: str | None = None
    lectura: float | None = None
    observacion: str | None = None       # desestadolectura (p.ej. "LECTURA NORMAL")


@dataclass
class FilaHistorico:
    """Una fila del HISTÓRICO DE CONSUMOS (un mes del record de facturación)."""
    mes_anio: str | None = None          # "Oct-25"
    modalidad: str | None = None         # "DIF. LECTURAS" | "ASIGNADO" | "PROMEDIO"
    volumen: float | None = None         # volumen facturado (m³)
    marca: str | None = None             # "RECLAMADO" | "REFACTURADO" | ""


# --- Bloques del documento (una caja del PDF = un sub-objeto) ---
@dataclass
class ClientePredio:
    suministro: str | None = None
    nombre_usuario: str | None = None    # propietario del predio (tarjeta)
    dni: str | None = None
    direccion: str | None = None
    mes_facturacion: str | None = None   # mes/año reclamado (mesanio del reclamo)
    categorias: list[CategoriaUso] = field(default_factory=list)  # matriz de 6 columnas


@dataclass
class FacturacionEvaluada:
    modalidad: str | None = None         # "DIF. LECTURAS" | "ASIGNADO" | "PROMEDIO"
    volumen_facturado: float | None = None
    lectura_anterior: LecturaHito = field(default_factory=LecturaHito)
    lectura_actual: LecturaHito = field(default_factory=LecturaHito)


@dataclass
class ValoresCalculados:
    dif_lecturas: float | None = None        # lectura_actual - lectura_anterior
    promedio_historico: float | None = None  # lecturapromedio del mes reclamado
    consumo_asignado: float | None = None    # consumo si modalidad=ASIGNADO, si no 0
    meses_promedio: str | None = None        # metodología (texto constante)
    observacion_consumo: str | None = None   # observación de identificación de consumo


@dataclass
class FichaMedidor:
    nro_serie: str | None = None
    estado: str | None = None                # desestadomed del mes reclamado
    marca: str | None = None
    modelo: str | None = None                # EMAPA no lo expone -> placeholder
    diametro: str | None = None
    modelo_homologacion: str | None = None   # placeholder
    nro_certificado: str | None = None       # placeholder
    fecha_instalacion: str | None = None
    fecha_verificacion: str | None = None    # placeholder (EMAPA suele no traerla)
    tipo_verificacion: str | None = None     # placeholder
    solicitante: str | None = None           # constante (EPS)
    uvm: str | None = None                    # placeholder


@dataclass
class Conexion:
    fecha_nacimiento: str | None = None          # ejecución de la conexión de agua
    fecha_instalacion_medidor: str | None = None
    nro_acta: str | None = None                  # placeholder (EMAPA no lo expone)


@dataclass
class SustentacionData:
    """Estructura completa del Informe de Sustentación del Régimen de
    Facturación por Usuario, organizada en las cajas del documento. Se ensambla
    (sin efectos secundarios) desde los datos ya analizados en memoria; el
    frontend la usa para construir el .docx con tablas."""
    cliente: ClientePredio = field(default_factory=ClientePredio)
    facturacion: FacturacionEvaluada = field(default_factory=FacturacionEvaluada)
    valores: ValoresCalculados = field(default_factory=ValoresCalculados)
    historico: list[FilaHistorico] = field(default_factory=list)
    medidor: FichaMedidor = field(default_factory=FichaMedidor)
    conexion: Conexion = field(default_factory=Conexion)
