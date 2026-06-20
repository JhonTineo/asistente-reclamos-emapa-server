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
Eres un especialista jurídico en
regulación SUNASS.

Debes analizar:

1. Reclamo.
2. Evidencias.
3. Artículos normativos.

No utilices conocimiento externo.

Responde únicamente JSON.

Formato:

{
  "clasificacion":"",
  "procede":true,
  "nivel_confianza":0.0,
  "articulos_aplicables":[],
  "fundamento":"",
  "requiere_revision_humana":false
}
"""
        ),
        (
            "user",
            """
RECLAMO

{detalle}


EVIDENCIAS

{evidencias}


ARTICULOS

{articulos}
"""
        )
    ]
)


class DictaminadorAgent:

    def __init__(self):

        self.llm = get_llm()

    def run(
        self,
        detalle,
        evidencias,
        articulos
    ):

        texto_articulos = "\n\n".join(
            [
                f"""
Articulo:
{x['payload'].get('article')}

Numeral:
{x['payload'].get('numeral')}

Texto:
{x['payload'].get('text')}
"""
                for x in articulos
            ]
        )

        if isinstance(evidencias, (dict, list)):
            texto_evidencias = json.dumps(
                evidencias,
                ensure_ascii=False,
                indent=2,
            )
        else:
            texto_evidencias = str(evidencias)

        chain = PROMPT | self.llm

        result = chain.invoke(
            {
                "detalle": detalle,
                "evidencias": texto_evidencias,
                "articulos": texto_articulos
            }
        )

        return json.loads(
            result.content
        )