from dataclasses import dataclass, field


@dataclass
class HallazgoInvestigacion:
    """Resultado de investigar un medio probatorio: el análisis que devuelve el
    modelo sobre la evidencia, en el contexto de un reclamo."""
    medio_id: str
    medio_nombre: str
    analisis: str
    tiempo: float | None = None
    articulos_sunass: list[dict] = field(default_factory=list)
