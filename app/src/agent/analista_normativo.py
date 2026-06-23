import logging
from langchain_core.messages import SystemMessage, HumanMessage
from core.llm import get_llm

logger = logging.getLogger("agent.analista_normativo")


class AnalistaNormativoAgent():
    role = "analista_normativo"

    def run(self, input_data: dict) -> dict:
        # input_data should contain: 'reclamo_text' and 'contexts' (list of payloads)
        reclamo = input_data.get("reclamo_text", "")
        contexts = input_data.get("contexts", [])
        modelo = input_data.get("modelo")

        llm = get_llm(model=modelo)

        contexts_text = "\n\n".join(
            f"=== Contexto #{i} ===\nTitle: {c.get('payload', {}).get('title')}\nText: {c.get('payload', {}).get('text', c.get('payload'))}"[:2000]
            for i, c in enumerate(contexts)
        )

        prompt = (
            "Eres un analista normativo. Recibe el reclamo del usuario y los extractos normativos relevantes. "
            "Analiza si la normativa aplica al reclamo, si procede, y devuelve: {'aplica': bool, 'justificacion': str, 'articulos': [lista_de_articulos]} en JSON.\n\n"
            f"RECLAMO:\n{reclamo}\n\nNORMATIVA RECUPERADA:\n{contexts_text}\n\nResponde SOLO con JSON."
        )

        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content="Analiza y devuelve el JSON pedido."),
        ])

        # Intentamos extraer JSON simple desde la respuesta
        import re, json

        match = re.search(r"\{.*\}", response.content, re.DOTALL)
        if not match:
            logger.warning("Analista no retornó JSON: %s", response.content[:200])
            return {"error": "No se pudo parsear JSON de la respuesta", "raw": response.content}

        try:
            data = json.loads(match.group())
            return {"result": data}
        except Exception as e:
            logger.warning("Error parseando JSON del analista: %s", e)
            return {"error": str(e), "raw": response.content}
