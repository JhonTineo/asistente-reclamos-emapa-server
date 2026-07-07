from dataclasses import dataclass, field


@dataclass
class TargetaLecturas:
    codcliente: str | None = None
    lecturapromedio: str | None = None
    tipopromedio: str | None = None
    nomtar: str | None = None
    destipoactividad: str | None = None
    errorLecturas: list[str] = field(default_factory=list)
    errorReinstalacion: list[str] = field(default_factory=list)
    errorEstadoServicio: list[str] = field(default_factory=list)
    atipicos: list[str] = field(default_factory=list)

    def observaciones_texto(self) -> list[str]:
        """Observaciones no vacías, en formato 'campo: valor'."""
        resultado = []
        for campo in ("obsinsinteriores", "observaciones", "obsperrepins"):
            valor = getattr(self, campo)
            if valor:
                resultado.append(f"{campo}: {valor}")
        return resultado
