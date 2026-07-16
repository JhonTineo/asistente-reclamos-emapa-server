from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProblemaNormado:
    """Un problema detectado en un medio probatorio, con su fundamentación
    normativa (se completa en la fase de fundamentación)."""
    tipo: str                          # "errorConsumo", "observacion", ...
    detalle: str                       # texto concreto CON cifras (para el LLM)

    # --- se llena en la fase de fundamentación normativa ---
    articulos: list[dict] = field(default_factory=list)   # recuperados de Qdrant
    accion: str | None = None
    responsable: str | None = None     # "cliente" | "empresa" | "no_determinable"
    base_legal: str | None = None


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


@dataclass
class BloqueMedio:
    """(entidad_medio, resumen, problemas[]) tipado: el aporte de un medio
    probatorio al informe."""
    medio_id: str
    medio_nombre: str
    entidad: dict                      # asdict() de la entidad de dominio
    resumen: str                       # resumen general (LLM) o frase predefinida
    problemas: list[ProblemaNormado] = field(default_factory=list)

    @property
    def tiene_problemas(self) -> bool:
        return len(self.problemas) > 0


@dataclass
class InformeAtencion:
    # --- metadatos (paso 2) ---
    numero: str
    fecha: datetime
    asunto: str
    reclamo: str
    suministro: str
    destinatario: str | None = None
    clasificacion: str | None = None
    motivo: str | None = None          # lo que reclama el cliente (JSON de búsqueda)
    objetivos: list["ObjetivoInvestigacion"] = field(default_factory=list)  # paso 2
    # --- cuerpo (se llena por medio, paso 3-4) ---
    bloques: list[BloqueMedio] = field(default_factory=list)
    ventana_meses: list[tuple[int, int]] = field(default_factory=list)
    veredicto: str | None = None       # "FUNDADO" | "INFUNDADO" (puerta lógica)
    conclusion: str | None = None      # texto de la conclusión (paso final)

    def agregar_bloque(self, bloque: BloqueMedio) -> None:
        self.bloques.append(bloque)
