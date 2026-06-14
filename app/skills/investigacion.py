"""
Skill de investigación de reclamos.
Genera prompts para análisis de medios probatorios.
"""


def generar_prompt_unificacion(reclamo_id: str, suministro_id: str, clasificacion: str, detalle: str) -> str:
    """
    Genera el prompt para el agente unificador que explica el problema del reclamo.
    """
    return (
        "Eres un agente especialista en análisis y explicación de reclamos de EMAPA.\n\n"
        "Tu tarea es analizar todos los resúmenes de medios probatorios y generar un informe "
        "unificado que explique el problema que generó el reclamo.\n\n"
        "El informe debe:\n"
        "1. Explicar claramente cuál fue el problema o problemas identificados.\n"
        "2. Referenciar los hallazgos de cada medio probatorio que sustenta la explicación.\n"
        "3. Indicar si el reclamo Procede, No Procede o Procede Parcialmente.\n"
        "4. Proponer acciones correctivas o de mejora si aplica.\n\n"
        "Contexto:\n"
        f"- Suministro ID: {suministro_id}\n"
        f"- Reclamo ID: {reclamo_id}\n"
        f"- Clasificación: {clasificacion}\n"
        f"- Detalle del reclamo: {detalle}\n\n"
        "Los resúmenes de los análisis de cada medio probatorio se te proporcionarán a continuación."
    )
