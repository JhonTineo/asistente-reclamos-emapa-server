from dataclasses import dataclass, field


@dataclass
class PuntosAgua:
    """Aparatos sanitarios (puntos de agua) contabilizados en una unidad de uso."""
    inodoro: float = 0.0
    lavado: float = 0.0
    ducha: float = 0.0
    urinario: float = 0.0
    bidet: float = 0.0
    grifo: float = 0.0
    cisterna: float = 0.0
    tanque: float = 0.0
    piscina: float = 0.0

    def total(self) -> float:
        return (
            self.inodoro + self.lavado + self.ducha + self.urinario + self.bidet
            + self.grifo + self.cisterna + self.tanque + self.piscina
        )

    def tiene_puntos(self) -> bool:
        return self.total() > 0


@dataclass
class InspeccionInterna:
    nroinspeccion: str | None = None
    fechainspeccion: str | None = None
    estadoabas: str | None = None
    catetar: str | None = None
    atipico: str | None = None
    obsinsinteriores: str | None = None
    observaciones: str | None = None
    obsperrepins: str | None = None
    puntos_agua: list[PuntosAgua] = field(default_factory=list)

    def observaciones_texto(self) -> list[str]:
        """Observaciones no vacías, en formato 'campo: valor'."""
        resultado = []
        for campo in ("obsinsinteriores", "observaciones", "obsperrepins"):
            valor = getattr(self, campo)
            if valor:
                resultado.append(f"{campo}: {valor}")
        return resultado
