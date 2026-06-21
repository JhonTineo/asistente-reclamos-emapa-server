"""
Skill de investigación de reclamos.
Genera prompts para análisis de medios probatorios.
"""

from app.tools.investigacion import _obtener_informes_struct


def generar_prompt_informe(informe_nombre: str, medios_requeridos: list[str], suministro_id: str, reclamo_id: str, clasificacion: str, detalle: str) -> str:
    """
    Genera el prompt del sistema para el agente que ejecutará una tarea de informe.
    """
    medios_texto = "\n".join(f"   - {m}" for m in medios_requeridos)

    return (
        f"Eres un agente especializado en análisis de medios probatorios para investigaciones de EMAPA.\n\n"
        f"Tu tarea es elaborar el informe: \"{informe_nombre}\"\n\n"
        f"Para este informe debes:\n"
        f"1. Analizar cada uno de los siguientes medios probatorios:\n"
        f"{medios_texto}\n"
        f"2. Extraer los hallazgos relevantes de cada medio.\n"
        f"3. Redactar una conclusión basada en el análisis de los medios.\n\n"
        f"Contexto del reclamo:\n"
        f"- Suministro ID: {suministro_id}\n"
        f"- Reclamo ID: {reclamo_id}\n"
        f"- Clasificación: {clasificacion}\n"
        f"- Detalle: {detalle}\n\n"
        f"Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional:\n"
        f'{{"hallazgos": ["hallazgo 1", "hallazgo 2", ...], "conclusion": "conclusión del análisis"}}'
    )


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


def obtener_tareas_informe(clasificacion: str, suministro_id: str, detalle: str) -> list[dict]:
    """
    Retorna la lista de tareas de informe para una clasificación dada.
    Cada tarea contiene: id, nombre, medios_requeridos, prompt, entrada, salida.
    """
    informes = _obtener_informes_struct(clasificacion)

    tareas = []
    for i, inf in enumerate(informes, 1):
        tarea_id = f"inf-{i}"
        reclamo_id = f"REC-{suministro_id}-{i}"
        nombre = inf["nombre"]
        medios_requeridos = inf["medios_requeridos"]
        prompt = generar_prompt_informe(nombre, medios_requeridos, suministro_id, reclamo_id, clasificacion, detalle)

        tareas.append({
            "id": tarea_id,
            "nombre": nombre,
            "medios_requeridos": medios_requeridos,
            "prompt": prompt,
            "entrada": {
                "suministro_id": suministro_id,
                "reclamo_id": reclamo_id,
                "clasificacion": clasificacion,
                "detalle": detalle,
            },
            "salida": "JSON con hallazgos (lista de strings) y conclusion (string)",
        })

    return tareas
