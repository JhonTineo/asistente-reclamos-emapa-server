from dataclasses import dataclass, field


@dataclass
class RegistroFacturacion:
    """Facturación de un mes (fila del record). Fuente única de verdad de los
    campos relevantes que se conservan del JSON de EMAPA."""
    anio: int | None = None
    mes: int | None = None
    tipopromedio: str | None = None      # 0 MEDIDO · 1 ASIGNADO · 2 PROMEDIADO
    consumo: float | None = None         # consumo real del periodo (m³)
    consumofac: float | None = None      # consumo facturado (m³)
    impmestotal: float | None = None     # importe facturado del mes (S/)
    catetar: str | None = None           # categoría tarifaria
    nromed: str | None = None            # medidor
    estadoservicio: str | None = None
    fechareg: str | None = None          # fecha de registro (desempate cronológico)
    impdeudareclamo: float | None = None  # >0 -> el mes tiene un reclamo asociado (RECLAMADO)
    c_impmesrebaja: float | None = None   # rebaja aplicada al mes (REFACTURADO)
    c_diarebaja: str | None = None        # fecha de la rebaja


@dataclass
class RecordFacturacion:
    # Escalares
    codcliente: str | None = None
    categoria: str | None = None              # categoría tarifaria (traducida: COMERCIAL, DOMESTICO…)
    formaPredominante: str | None = None      # forma de facturación más frecuente
    totalMeses: int = 0
    totalPromediados: int = 0                  # meses NO facturados por lectura
    # Hallazgos: SOLO los meses "con problema" (no el detalle de todos los meses),
    # para que al LLM le lleguen únicamente los errores encontrados.
    mesesPromediados: list[str] = field(default_factory=list)  # meses facturados por promedio
    rachaPromediados: list[str] = field(default_factory=list)  # racha promedio -> lectura (posible origen del reclamo)

    # Detalle mensual completo de la ventana analizada (para mostrar en tabla).
    registros: list[dict] = field(default_factory=list)
