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
    # --- Resultado de la audiencia (mismos campos que la pantalla de SYSCO) ---
    asistio: bool | None = None          # ASISTIÓ
    subsiste: bool | None = None         # ¿SUBSISTE EL RECLAMO? (False = acepta la propuesta)
    por_telefono: bool = False           # CONCILIACIÓN X TELÉFONO
    fecha_audiencia: str | None = None   # fecha de la audiencia (texto, p.ej. 26/10/2026)
    # Frase técnica "AL HABERSE VERIFICADO QUE ..." que redactó la IA; se
    # guarda para rearmar el texto con el formato cuando cambia el resultado.
    sustento: str | None = None
    # True si el analista editó a mano el texto: entonces no se reescribe solo.
    propuesta_editada: bool = False
