from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.src.core.model.reclamo import Reclamo
from app.src.core.model.conciliacion import Conciliacion


EstadoEvaluacion = Literal[
    "pendiente", "completada", "requiere_evidencia", "requiere_revision",
    "error_evaluacion",
]


@dataclass
class MotivoEvaluacion:
    codigo: str
    objetivos_afectados: list[int] = field(default_factory=list)
    descripcion: str = ""
    evidencia_pendiente: str | None = None
    accion_necesaria: str | None = None


@dataclass
class ProblemaNormado:
    """Un problema detectado en un medio probatorio, con su fundamentación
    normativa (se completa en la fase de fundamentación)."""
    tipo: str                          # "errorConsumo", "observacion", ...
    detalle: str                       # texto concreto CON cifras (para el LLM)
    fuente: str | None = None
    texto_original: str | None = None

    # --- se llena en la fase de fundamentación normativa ---
    # `seleccionado`: el problema fue elegido como determinante (1-3) y por tanto
    # se fundamenta (RAG + párrafo). Los no seleccionados se muestran igual como
    # tarjeta, pero sin artículos.
    seleccionado: bool = False
    articulos: list[dict] = field(default_factory=list)   # recuperados de Qdrant
    accion: str | None = None
    responsable: str | None = None     # "cliente" | "empresa" | "no_determinable"
    base_legal: str | None = None

    # Identificador estable en el registro de hechos del caso ("H-tl-01"). Lo
    # asigna el store al registrar el bloque (ver services/informe/hechos.py);
    # es lo que citarán los artefactos generados y permite saber qué partes del
    # informe dependen de cada hecho.
    id: str | None = None
    # "problema": anomalía detectada (lo que hoy se muestra como tarjeta).
    # "constatacion": hecho neutro o favorable verificado por reglas (p.ej. "en
    # 09/2026 se facturó por lectura real"). Ambos son evidencia del caso; solo
    # los problemas cuentan como "hallazgos" del medio.
    clase: str = "problema"
    # Mes al que se refiere el hecho ("2026-09"), si aplica, y el dato duro que
    # lo sustenta (cifras), para que los pasos posteriores no dependan del texto.
    periodo: str | None = None
    valor: dict | None = None


@dataclass
class ObjetivoInvestigacion:
    """Objetivo concreto y verificable derivado del motivo del reclamo. Guía la
    investigación (qué buscar en cada medio)."""
    id: int
    descripcion: str
    medio: str | None = None           # medio que lo responde
    determinante: bool = False         # ¿decide si el reclamo procede?
    # se llenan al evaluarlo contra los hallazgos (fase de conclusión)
    resultado: str | None = None
    evidencia: str | None = None

    @property
    def medios_relacionados(self) -> tuple[str, ...]:
        """Las inspecciones aportan contexto complementario sin sustituirse."""
        if self.medio in {"inspeccion_interna", "inspeccion_externa"}:
            return ("inspeccion_interna", "inspeccion_externa")
        return (self.medio,) if self.medio else ()


@dataclass
class BloqueMedio:
    """(entidad_medio, resumen, problemas[]) tipado: el aporte de un medio
    probatorio al informe."""
    medio_id: str
    medio_nombre: str
    entidad: dict                      # asdict() de la entidad de dominio
    resumen: str                       # resumen general (LLM) o frase predefinida
    problemas: list[ProblemaNormado] = field(default_factory=list)
    # Hechos neutros o favorables (clase="constatacion"), ver
    # services/pre_proces/constataciones.py.
    constataciones: list[ProblemaNormado] = field(default_factory=list)

    @property
    def tiene_problemas(self) -> bool:
        return len(self.problemas) > 0

    @property
    def hechos(self) -> list[ProblemaNormado]:
        """Toda la evidencia del medio: problemas y constataciones."""
        return [*self.problemas, *self.constataciones]


@dataclass
class InformeAtencion:
    # --- metadatos (paso 2) ---
    numero: str
    fecha: datetime
    asunto: str
    reclamo: str                       # código del reclamo (codreclamo)
    suministro: str
    destinatario: str | None = None
    datos_reclamo: Reclamo | None = None
    medios_probatorios: list[dict[str, str]] = field(default_factory=list)
    objetivos: list["ObjetivoInvestigacion"] = field(default_factory=list)  # paso 2
    # --- cuerpo (se llena por medio, paso 3-4) ---
    bloques: list[BloqueMedio] = field(default_factory=list)
    # PDF temporal cargado para el medio técnico operacional. Solo existe
    # mientras la atención del reclamo permanezca abierta.
    documento_tecnico_operacional: dict | None = None
    ventana_meses: list[tuple[int, int]] = field(default_factory=list)
    # Párrafo de fundamentación normativa: se genera tras analizar los medios
    # (a partir de los hallazgos determinantes) y se renderiza como punto final,
    # antes de la conclusión, tal como el punto normativo de los informes reales.
    fundamentacion_normativa: str | None = None
    estado_evaluacion: EstadoEvaluacion = "pendiente"
    motivos_evaluacion: list[MotivoEvaluacion] = field(default_factory=list)
    mensaje_evaluacion: str | None = None
    origen_decision: str | None = None  # "automatica" | "historica_sysco"
    historial_decisiones: list[dict] = field(default_factory=list)
    veredicto: str | None = None       # "FUNDADO" | "INFUNDADO" (puerta lógica)
    # Dictamen que sustenta el veredicto (pasos/dictamen.py, Dictamen.a_dict()):
    # factores por criterio, hechos citados, regla que decidió y motivos.
    dictamen: dict | None = None
    conclusion: str | None = None      # texto de la conclusión (paso final)
    # Texto completo recuperado de SYSCO. Cuando existe, es la fuente original
    # que debe devolverse al frontend; los tres campos anteriores son su vista
    # estructurada para que conciliación y resolución puedan reutilizar el mismo
    # flujo que un informe generado por este servicio.
    informe_texto_original: str | None = None
    # --- pasos posteriores a la conclusión (paso 4-5) ---
    propuesta_conciliacion: Conciliacion | None = None
    resolucion: str | None = None
    # Id de la pestaña/sesión del frontend que abrió este reclamo (ver
    # InformeAtencionStore.crear_metadata). Permite distinguir "la misma
    # pestaña recargando" de "otra ventana intentando atender el mismo
    # reclamo en paralelo".
    sesion_id: str | None = None
    # Usuario de EMAPA que inició la atención. Se usa solo para organizar la
    # cola en la interfaz; no constituye una regla de autorización.
    creado_por: str | None = None
    # --- memoria del caso (persistencia) ---
    # Último número de hecho usado por medio ({"tarjeta_lectura": 3}). Nunca
    # retrocede, para que un ID de hecho reemplazado no se reutilice.
    secuencia_hechos: dict[str, int] = field(default_factory=dict)
    # Origen de los textos editados o recuperados: tipo de artefacto ->
    # (origen, firma del texto). El origen solo vale mientras el texto siga
    # siendo el mismo; si un paso lo regenera, vuelve a ser "generado".
    marcas_origen: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def clasificacion(self) -> str | None:
        return self.datos_reclamo.clasificacion_reclamo if self.datos_reclamo else None

    @property
    def motivo(self) -> str | None:
        return self.datos_reclamo.motivo_reclamo if self.datos_reclamo else None

    def agregar_bloque(self, bloque: BloqueMedio) -> None:
        self.bloques.append(bloque)
