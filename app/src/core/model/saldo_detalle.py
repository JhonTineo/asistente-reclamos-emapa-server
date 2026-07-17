from dataclasses import dataclass, field


@dataclass
class SaldoMensual:
    """Saldo de un mes (fila del saldo-detalle). Fuente única de verdad de los
    campos relevantes que se conservan del JSON de EMAPA."""
    anio: int | None = None
    mes: int | None = None
    impmesagu: float | None = None       # importe de agua del mes (S/)
    impmesalc: float | None = None       # importe de alcantarillado/desagüe del mes (S/)
    impmesmora: float | None = None      # importe por mora del mes (S/)
    impmestotal: float | None = None     # importe facturado del mes, sin mora (S/)
    imptotal: float | None = None        # importe total a pagar del mes, con mora (S/)
    estadosaldo: str | None = None       # 001 PAGADO · distinto de 001 => pendiente
    tiposervicio: str | None = None      # des_tiposervicio (p.ej. "AGUA Y DESAGUE")


@dataclass
class SaldoDetalle:
    # Escalares
    codcliente: str | None = None
    tipoServicio: str | None = None            # tipo de servicio predominante
    totalMeses: int = 0
    # Hallazgos: SOLO los meses "con problema" (no el detalle de todos los meses),
    # para que al LLM le lleguen únicamente los errores encontrados.
    cobroIndebido: list[str] = field(default_factory=list)   # importe por servicio no prestado
    mora: list[str] = field(default_factory=list)            # cobro de mora además del importe del mes
    mesesNoPagados: list[str] = field(default_factory=list)  # meses con saldo pendiente

    # Detalle mensual completo de la ventana analizada (para mostrar en tabla).
    registros: list[dict] = field(default_factory=list)
