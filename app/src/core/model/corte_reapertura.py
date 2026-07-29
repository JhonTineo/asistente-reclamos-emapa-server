from dataclasses import dataclass, field

@dataclass
class RegistroCorteReapertura:
    anio: int | None = None
    mes: int | None = None
    item: int | None = None              # id del evento (trazabilidad)
    tipooperacion: str | None = None     # 001 corte · 002 reapertura
    codoperacion: str | None = None      # 001 real · 003 prórroga
    destipooperacion: str | None = None  # etiqueta legible
    estadoservicio: str | None = None    # activo / cortado
    fechacorte: str | None = None        # fecha del evento (o límite de prórroga)
    fechareg: str | None = None          # fecha de registro real
    lecturaultima: float | None = None   # lectura al corte (cruza con la tarjeta)
    observacion: str | None = None       # motivo (ej. "Prorroga por reclamo Nro. …")

@dataclass
class CorteReapertura:
    # Escalares
    # Indica que la API devolvió registros pero ninguno cae en la ventana analizada.
    sinRegistrosEnVentana: bool = False
    totalRegistrosOriginales: int = 0
    # Conteos en la ventana
    totalCortes: int = 0
    totalReaperturas: int = 0
    totalProrrogas: int = 0
    # Listas agrupadas por mes ("AAAA-MM: detalle")
    cortes: list[str] = field(default_factory=list)        # meses con corte (fecha, lectura)
    reaperturas: list[str] = field(default_factory=list)   # meses con reapertura
    prorrogas: list[str] = field(default_factory=list)     # meses con prórroga (+ motivo)
    # Hallazgos
    mesesCortados: list[str] = field(default_factory=list) # meses de la ventana con servicio cortado
    reclamosPrevios: list[str] = field(default_factory=list) # observaciones que citan "Reclamo Nro. …"

    # Detalle de eventos completo de la ventana analizada (para mostrar en tabla).
    registros: list[dict] = field(default_factory=list)