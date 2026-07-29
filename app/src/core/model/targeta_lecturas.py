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
    desestadolectura: str | None = None    # texto de estadolectura (p.ej. "LECTURA NORMAL")
    desestadoservicio: str | None = None   # texto de estadoservicio
    desestadomed: str | None = None        # texto de estadomed


@dataclass
class TargetaLecturas:
    # Escalares constantes del suministro.
    nomtar: str | None = None
    destipoactividad: str | None = None
    tipopromedio: str | None = None
    propietario: str | None = None                  # propietariocabecera — titular del predio (NOMBRE DEL USUARIO)
    direccion: str | None = None                    # descodcallecabecera + " " + nrocallecabecera
    categoria: str | None = None                    # catetarcabecera (código de categoría tarifaria)
    diametro: str | None = None                     # descoddiametrocabecera
    marca_medidor: str | None = None                # desmarcamedcabecera
    tipo_medidor: str | None = None                 # destipomedcabecera (lo más cercano a "modelo" que trae EMAPA)
    nro_medidor: str | None = None                  # nromedcabecera
    fecha_instalacion_medidor: str | None = None    # fechainsmedcabecera
    fecha_instalacion_conexion: str | None = None   # fechainsconagucabecera (nacimiento de la conexión de agua)
    fecha_verificacion: str | None = None           # fechacontrslaborcabecera / fechacontrscampocabecera (suele venir null)
    tipo_verificacion: str | None = None            # desresultadocontrastacioncabecera (suele venir null)

    # Hallazgos detectados en la ventana de análisis.
    # - consumo atípico (> 2× promedio) · doble consumo (igual entre dos meses concecutivos)
    errorConsumo: list[str] = field(default_factory=list)
    # - consumo negativo · error de fecha · sin lectura normal
    errorLecturas: list[str] = field(default_factory=list)
    # - cambio de medidor con consumo atípico
    errorReinstalacion: list[str] = field(default_factory=list)
    # - estado del medidor · estado del servicio
    errorServicio: list[str] = field(default_factory=list)
    # - fuga no visible ya reparada: consumo elevado que retorna al promedio
    #   histórico en un mes posterior (sustenta refacturación por promedio, Art. 88.3)
    fugaReparada: list[str] = field(default_factory=list)
    # - observaciones de lectura
    obslectura: list[str] = field(default_factory=list)

    # Detalle mensual completo de la ventana analizada (para mostrar en tabla).
    registros: list[dict] = field(default_factory=list)