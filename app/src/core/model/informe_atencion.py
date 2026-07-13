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
    # --- cuerpo (se llena por medio, paso 3-4) ---
    bloques: list[BloqueMedio] = field(default_factory=list)
    conclusion: str | None = None      # fundado / infundado (paso final)

    def agregar_bloque(self, bloque: BloqueMedio) -> None:
        self.bloques.append(bloque)
