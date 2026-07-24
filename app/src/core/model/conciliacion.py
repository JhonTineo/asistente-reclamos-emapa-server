from dataclasses import dataclass


@dataclass
class Conciliacion:
    """Datos de la conciliación entre la empresa y el reclamante: la propuesta
    de la empresa, la postura del reclamante frente a ella, y los puntos en
    los que llegaron (o no) a un acuerdo.

    Solo ``propuesta_empresa`` nace vacía (la redacta el LLM en
    POST /conciliacion/propuesta); los demás campos arrancan con el texto
    habitual del caso conforme (aceptación total), y se editan a mano vía
    PATCH /conciliacion/datos cuando el caso real difiere."""
    propuesta_empresa: str = ""
    propuesta_reclamante: str = "ACEPTAR LA PROPUESTA DE LA EPS"
    puntos_acuerdo: str = "LO PROPUESTO POR LA EPS"
    puntos_desacuerdo: str = "NINGUNO"
    observaciones: str = "NINGUNO"
