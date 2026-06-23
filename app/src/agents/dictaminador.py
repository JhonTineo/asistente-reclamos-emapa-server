import json
from langchain_core.prompts import (ChatPromptTemplate)
from app.src.core.llm import get_llm

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
4. Resumen analítico de servicio anual brindado por EMAPA.

No utilices conocimiento externo.

Responde únicamente JSON.

Formato:

{{
    "clasificacion":"",
    "procede":true,
    "nivel_confianza":0.0,
    "articulos_aplicables":[],
    "fundamento":"",
    "requiere_revision_humana":false
}}
"""
        ),
        (
            "user",
            """
RECLAMO

{detalle}

CLASIFICACIÓN DE RECLAMO

{clasificacion}


EVIDENCIAS

{evidencias}


ARTICULOS

{articulos}

RESUMEN ANALÍTICO DE SERVICIO ANUAL BRINDADO POR EMAPA

{resumen_servicio}
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
        clasificacion,
        evidencias,
        articulos,
        resumen_servicio
    ):

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
                "articulos": articulos,
                "resumen_servicio": resumen_servicio,
                "clasificacion": clasificacion
            }
        )

        return json.loads(
            result.content
        )