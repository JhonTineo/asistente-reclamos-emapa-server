from dataclasses import dataclass, field

@dataclass
class LecturaMensual:
    anio: int | None = None
    mes: int | None = None
    fechalecturault: str | None = None     # Validar que la fecha de ultima lectura pertenezca al mes y año de la lectura.
    lecturaanterior: float | None = None
    lecturaultima: float | None = None
    consumo: float | None = None           # Validar consumos atipicos, doble consumo, consumo negativo
    lecturapromedio: float | None = None
    estadoservicio: str | None = None      # Validar que el estado del servicio
    estadomed: str | None = None           # Validar que el estado del medidor
    estadolectura: str | None = None       # Validar que el estado de la lectura sea normal
    nromed: str | None = None              # nº de medidor (para detectar cambio/reinstalación)
    obslectura: str | None = None


@dataclass
class TargetaLecturas:
    # Escalares constantes del suministro.
    codcliente: str | None = None
    nomtar: str | None = None
    destipoactividad: str | None = None
    tipopromedio: str | None = None

    # Hallazgos detectados en la ventana de análisis.
    # - consumo atípico (> 2× promedio) · doble consumo (igual entre dos meses concecutivos)
    errorConsumo: list[str] = field(default_factory=list)
    # - consumo negativo · error de fecha · sin lectura normal
    errorLecturas: list[str] = field(default_factory=list)
    # - cambio de medidor con consumo atípico
    errorReinstalacion: list[str] = field(default_factory=list)
    # - estado del medidor · estado del servicio
    errorServicio: list[str] = field(default_factory=list)
    # - observaciones de lectura
    obslectura: list[str] = field(default_factory=list)