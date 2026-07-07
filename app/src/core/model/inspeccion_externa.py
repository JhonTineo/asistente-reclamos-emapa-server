from dataclasses import dataclass


@dataclass
class InspeccionExterna:
    nroinspeccion: str | None = None
    fechainspeccion: str | None = None
    funcionamed: str | None = None
    fugas: str | None = None
    tipofugas: str | None = None
    observacionmed: str | None = None
    estadocaja: str | None = None
    observacionsum: str | None = None
    estconexion: str | None = None
    nomresponsable: str | None = None
    atipico: str | None = None

    def observaciones(self) -> list[str]:
        """Observaciones no vacías, en formato 'campo: valor'."""
        resultado = []
        for campo in ("observacionmed", "observacionsum"):
            valor = getattr(self, campo)
            if valor:
                resultado.append(f"{campo}: {valor}")
        return resultado
