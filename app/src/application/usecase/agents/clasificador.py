import json
from langchain_core.prompts import (ChatPromptTemplate)
from app.src.application.services.rag.retriever import Retriever
from app.src.application.adapters.llm import get_llm

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
Eres un especialista técnico en reclamos SUNASS.

Debes clasificar el reclamo utilizando EXCLUSIVAMENTE
las categorías definidas en el reglamento proporcionado.

Reglas:

1. No inventes categorías.
2. No uses conocimiento externo.
3. Si no existe una categoría aplicable responde NO_CLASIFICADO.
4. Selecciona la categoría más específica posible.
5. Indica la sección exacta utilizada.

Responde únicamente JSON.

Formato:

{{
    "tipo":"",
    "subtipo":"",
    "justificacion":""
}}
"""
        ),
        (
            "user",
            """
RECLAMO

{detalle}

REGLAMENTO

{anexo1_tipos_reclamo}
"""
        )
    ]
)

class ClasificadorAgent:
    
    def __init__(self):

        self.llm = get_llm()
        self.retriever = Retriever()

    def run(
    self,
    detalle: str
    ):
        query = f"Detalle del reclamo: {detalle}\n\nClasifica este reclamo según el reglamento de SUNASS."
        anexo1_tipos_reclamo =self.retriever.retrieve(
            collection_name = "anexo1_tipos_reclamo",
            query=query,
            top_k=5
        )

        tipos_reclamos_context = self.retriever.build_context(
            collection_name="anexo1_tipos_reclamo",
            results=anexo1_tipos_reclamo
        )

        response = self.llm.invoke(
            PROMPT.format_messages(
                detalle=detalle,
                anexo1_tipos_reclamo=tipos_reclamos_context
            )
        )
        print("anexo1_tipos_reclamo:", anexo1_tipos_reclamo[:10])
        print("=" * 80)
        print("TIPO RESPONSE:", type(response))
        print("RESPONSE:", response)
        print("=" * 80)

        try:
            print("CONTENT:")
            print(repr(response.content))

            resultado = json.loads(response.content)

            print("JSON OK:")
            print(resultado)

            return resultado

        except Exception as e:
            print("ERROR PARSEANDO:")
            print(type(e))
            print(e)

            return {
                "tipo": "ERROR",
                "subtipo": "ERROR",
                "justificacion": str(e)
            }