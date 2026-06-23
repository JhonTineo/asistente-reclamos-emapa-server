import json
import re
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from app.src.core.llm import get_llm

ANEXO_PATH = Path(__file__).parent.parent / "storage" / "anexo1_tipos_reclamo.md"


SECCIONES_KEYWORDS = {
    "I.A": [
        "factura", "facturación", "facturado", "cobro", "cobrar",
        "consumo", "consumir", "consumidor", "volumen", "lectura",
        "tarifa", "tarifario", "categoría", "asignación", "asignado",
        "promedio", "medidor", "registro", "medición", "medir",
        "recibo", "pagado", "pago", "procesado", "entidad",
        "concepto", "conceptos", "cargo", "cargos", "unidad", "unidades",
        "no facturado", "no se facturó", "cierre", "cerrado",
        "servicio cerrado", "cruce", "suministro cruzado",
    ],
    "I.B": [
        "acceso", "acceso al servicio", "instalación", "instalar",
        "conexión", "conectar", "contrato", "contratación",
        "factibilidad", "informe de factibilidad", "no se admite",
        "trámite", "admitido", "plazo", "no suscribe",
        "micromedición", "micromedicion", "medidor instalado",
        "instalación del medidor", "reinstalación", "retiro del medidor",
        "verificación", "prueba", "corte", "suspensión", "suspendido",
        "cortado", "indebido", "rehabilitación", "rehabilitar",
        "recibo", "entrega del recibo", "no me llegó", "información",
        "informar", "SUNASS", "dato", "datos",
    ],
    "II.A": [
        "filtración", "filtracion", "filtro", "agua externa",
        "predio", "infiltración", "infiltracion",
    ],
    "II.B": [
        "agua potable", "agua", "potable", "fuga", "fugas",
        "conexión domiciliaria", "mantenimiento", "deterioro",
        "daño", "caja de medidor", "reubicación", "reubicar",
        "ampliación", "diametro", "diámetro", "estudio de factibilidad",
    ],
    "II.C": [
        "alcantarillado", "desagüe", "drenaje", "atoro", "atoros",
        "atascar", "caja de registro", "registro", "conexión de alcantarillado",
    ],
}


SYSTEM_PROMPT = """Eres un clasificador especialista en reclamos de servicios de saneamiento.
    Tu tarea es clasificar el reclamo del usuario según la sección del Reglamento SUNASS que le corresponde.
    REGLAS:
    1. Analiza cuidadosamente el detalle del reclamo y la sección del anexo proporcionada.
    2. Identifica el tipo de problema describedo en el reclamo.
    3. Devuelve ÚNICAMENTE código + nombre del tipo de reclamo.
    4. No agreges explicaciones ni justificaciones.
    5. Si el reclamo no encaja exactamente en ningún tipo, busca el más cercano.
    FORMATO DE RESPUESTA (solo este texto, sin JSON ni nada más):
    [código] - [nombre]
    Ejemplo de respuestas válidas:
    I.A.1 - Consumo medido
    I.A.3 - Asignación de Consumo
    II.B.1 - Fugas en conexión domiciliaria
"""

USER_PROMPT = """ANEXO 1 - Tipos de Reclamos (sección relevante):
    {anexo_seccion}
    ---
    RECLAMO A CLASIFICAR:
    {detalle}
    ---
    Responde solo con el código y nombre del tipo de reclamo que corresponde.
"""


def _preclasificar_seccion(detalle: str) -> str:
    """
    Usa keywords para determinar qué sección del anexo es más relevante.
    Retorna el código de sección (ej: "I.A", "I.B", "II.A", etc.)
    """
    detalle_lower = detalle.lower()

    seccion_scores = {}

    for seccion, keywords in SECCIONES_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in detalle_lower:
                score += 1
        if score > 0:
            seccion_scores[seccion] = score

    if not seccion_scores:
        return "I.A"

    return max(seccion_scores, key=seccion_scores.get)


def _cargar_anexo_seccion(seccion: str) -> str:
    """
    Lee el anexo y retorna solo la sección correspondiente.
    """
    try:
        contenido = ANEXO_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""

    lineas = contenido.split("\n")
    resultado = []
    seccion_actual = None
    en_seccion = False

    if seccion == "I.A":
        marcas_inicio = ["## I. COMERCIALES", "### A. Relativos a la Facturación"]
        marca_fin = ["### B. No Relativos a la Facturación", "## II. OPERACIONALES"]
    elif seccion == "I.B":
        marcas_inicio = ["### B. No Relativos a la Facturación"]
        marca_fin = ["## II. OPERACIONALES"]
    elif seccion == "II.A":
        marcas_inicio = ["## II. OPERACIONALES", "### A. Filtraciones"]
        marca_fin = ["### B. Problemas en el servicio"]
    elif seccion == "II.B":
        marcas_inicio = ["### B. Problemas en el servicio de agua potable"]
        marca_fin = ["### C. Problemas en el servicio de alcantarillado"]
    elif seccion == "II.C":
        marcas_inicio = ["### C. Problemas en el servicio de alcantarillado"]
        marca_fin = []
    else:
        return contenido

    for linea in lineas:
        es_marca_fin = any(linea.strip().startswith(f) for f in marca_fin)

        if any(linea.strip().startswith(m) for m in marcas_inicio):
            en_seccion = True

        if en_seccion and es_marca_fin and marca_fin:
            break

        if en_seccion:
            resultado.append(linea)

    return "\n".join(resultado).strip()


def _llm_clasificar(anexo_relevante: str, detalle: str) -> dict:
    """
    Envía el anexo relevante y el detalle a Ollama para clasificación.
    """
    llm = get_llm()

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("user", USER_PROMPT),
    ])

    chain = prompt | llm

    try:
        result = chain.invoke({
            "anexo_seccion": anexo_relevante,
            "detalle": detalle,
        })

        respuesta = result.content.strip()

        return {
            "success": True,
            "respuesta": respuesta,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _parsear_respuesta(respuesta: str) -> dict:
    """
    Parsea la respuesta del LLM para extraer código y nombre.
    """
    respuesta = respuesta.strip()

    match = re.match(r"^([IVX]+\.[A-Z](?:\.\d+)?)\s*-\s*(.+)$", respuesta)

    if match:
        return {
            "codigo": match.group(1),
            "nombre": match.group(2).strip(),
        }

    return {
        "codigo": "UNKNOWN",
        "nombre": respuesta,
    }


def clasificar_reclamo(detalle: str) -> dict:
    """
    Función principal para clasificar un reclamo usando LLM.

    Args:
        detalle: Texto del reclamo del usuario

    Returns:
        dict con:
            - success: bool
            - codigo: str (ej: "I.A.3")
            - nombre: str (ej: "Asignación de Consumo")
            - seccion: str (ej: "I.A")
            - error: str (si success=False)
    """
    if not detalle or len(detalle.strip()) < 10:
        return {
            "success": False,
            "error": "El detalle del reclamo es muy corto o está vacío",
            "codigo": None,
            "nombre": None,
            "seccion": None,
        }

    seccion = _preclasificar_seccion(detalle)
    anexo_seccion = _cargar_anexo_seccion(seccion)

    if not anexo_seccion:
        return {
            "success": False,
            "error": "No se pudo cargar el anexo",
            "codigo": None,
            "nombre": None,
            "seccion": seccion,
        }

    resultado = _llm_clasificar(anexo_seccion, detalle)

    if not resultado["success"]:
        return {
            "success": False,
            "error": resultado["error"],
            "codigo": None,
            "nombre": None,
            "seccion": seccion,
        }

    parsed = _parsear_respuesta(resultado["respuesta"])

    return {
        "success": True,
        "codigo": parsed["codigo"],
        "nombre": parsed["nombre"],
        "seccion": seccion,
        "error": None,
    }
