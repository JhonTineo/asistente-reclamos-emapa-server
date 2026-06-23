import json

from langchain_core.prompts import (
    ChatPromptTemplate
)

from app.core.llm import get_llm

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
Eres un especialista técnico en servicio de SUNASS (Superintendencia Nacional de Servicios de Saneamiento
).

Debes analizar:
La información histórica de un año de consumo, record de facturación, cortes, reaperturas, inspecciones internas, inspecciones externas, saldo del cliente, tarjeta de lectura, 
en el intervalo de tiempo de 12 meses, y generar un resumen analítico del servicio anual brindado por EMAPA al cliente. De existir irregularidades, señalar el periodo en que se produjeron, la naturaleza de la irregularidad y su posible impacto en la calidad del servicio.
No utilices conocimiento externo.

Responde únicamente JSON.

Formato:

{{
"resumen_servicio":"Texto del resumen analítico del servicio anual brindado por EMAPA al cliente, incluyendo cualquier irregularidad identificada, su periodo, naturaleza e impacto."
}}
"""
        ),
        (
            "user",
            """
INFORMACIÓN HISTÓRICA DE SERVICIO ANUAL BRINDADO POR EMAPA EN FORMATO JSON:
{contexto_emapa}
"""
        )
    ]
)


class ResumenTecnicoAgent:

    def __init__(self):

        self.llm = get_llm()

    def run(
        self,
        contexto_emapa: dict,
    ):
        response = self.llm.invoke(
            PROMPT.format_messages(
                contexto_emapa=json.dumps(contexto_emapa)
            )
        )

        try:
            resultado = json.loads(response.content)
            return resultado.get("resumen_servicio", "")
        except json.JSONDecodeError:
            return "Error: No se pudo generar un resumen técnico válido."