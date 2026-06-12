import json
import re
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate
from app.core.llm import get_llm
from app.schemas.reclamo import ClasificarReclamoResponse

ANEXO1_PATH = Path(__file__).parent.parent / "storage" / "anexo1_tipos_reclamos.md"

PROMPT_CLASIFICACION = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Eres un especialista en clasificación de reclamos de una empresa de servicios de agua "
            "potable y alcantarillado (EMAPA). Tu tarea es analizar el detalle del reclamo presentado "
            "por un cliente y clasificarlo según la documentación normativa del Anexo 1.\n\n"
            "Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional antes ni después. "
            "El JSON debe tener exactamente estos campos:\n"
            '  "clasificacion": el tipo de reclamo según el Anexo 1\n'
            '  "razonamiento": explicación breve de por qué se clasifica así\n\n'
            "Documentación normativa de referencia (Anexo 1 - Problemas de Alcance Particular):\n\n"
            "{anexo1}",
        ),
        (
            "user",
            "Clasifica el siguiente reclamo:\n\n"
            "ID de Reclamo: {reclamo_id}\n"
            "Detalle del reclamo: {detalle}",
        ),
    ]
)


def _cargar_anexo1() -> str:
    return ANEXO1_PATH.read_text(encoding="utf-8")


def _extraer_json(texto: str) -> dict:
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        raise ValueError(f"No se encontró JSON en la respuesta: {texto[:200]}")
    return json.loads(match.group())


def clasificar_reclamo(reclamo_id: str, detalle: str) -> ClasificarReclamoResponse:
    llm = get_llm()
    chain = PROMPT_CLASIFICACION | llm

    response = chain.invoke(
        {
            "anexo1": _cargar_anexo1(),
            "reclamo_id": reclamo_id,
            "detalle": detalle,
        }
    )

    data = _extraer_json(response.content)
    return ClasificarReclamoResponse(
        reclamo_id=reclamo_id,
        clasificacion=data["clasificacion"],
        razonamiento=data["razonamiento"],
    )
