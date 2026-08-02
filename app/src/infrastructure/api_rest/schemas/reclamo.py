"""Schemas específicos del router de reclamos: clasificación rápida (por
reglas, sin LLM) y cierre de la atención."""

from pydantic import BaseModel


class ClasificarRapidoRequest(BaseModel):
    motivo: str
    desc_tipo_reclamo: str | None = None
    # Si el reclamo ya fue clasificado por el personal, se respeta y no se
    # vuelve a clasificar (caso: reclamos presenciales ya tipificados).
    des_cod_reclamo: str | None = None


class ClasificarRapidoResponse(BaseModel):
    tipo: str | None
    confianza: str            # "definida" | "alta" | "media" | "baja" | "nula"
    metodo: str               # "sistema" (ya venía) | "reglas"
    score: int = 0
    candidatos: list[dict] = []


class FinalizarAtencionResponse(BaseModel):
    codreclamo: str
    eliminado: bool


class ReclamoEnMemoria(BaseModel):
    """Metadatos mínimos de un reclamo con informe vivo en memoria del servidor."""
    codreclamo: str
    codcliente: str | None = None
    sesion_id: str | None = None
    veredicto: str | None = None


class ReclamosEnMemoriaResponse(BaseModel):
    reclamos: list[ReclamoEnMemoria]
