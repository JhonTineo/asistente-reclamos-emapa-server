import logging
import json
from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT
logger = logging.getLogger("agent.analista_normativo")


class AnalistaNormativoAgent():
    def __init__(self, llm_router: LlmRouterService):
        self.llm_router = llm_router

    def run(self, input_data: dict) -> dict:
        reclamo = input_data.get("reclamo_text", "")
        contexts = input_data.get("contexts", [])
        modelo = input_data.get("modelo") or MODELO_EXTERNO_DEFAULT
        contexts_text = "\n\n".join(
            f"=== Contexto #{i} ===\nTitle: {c.get('payload', {}).get('title')}\nText: {c.get('payload', {}).get('text', c.get('payload'))}"[:2000]
            for i, c in enumerate(contexts)
        )

        prompt = (
            "Eres un analista normativo. Recibe el reclamo del usuario y los extractos normativos relevantes. "
            "Analiza si la normativa aplica al reclamo, si procede, y devuelve: {'aplica': bool, 'justificacion': str, 'articulos': [lista_de_articulos]} en JSON.\n\n"
            f"RECLAMO:\n{reclamo}\n\nNORMATIVA RECUPERADA:\n{contexts_text}\n\nResponde SOLO con JSON."
        )

        try:
            response_text = self.llm_router.generar_json(
                mensajes=[
                    MensajeLLM(rol="system", contenido=prompt),
                    MensajeLLM(rol="user", contenido="Analiza y devuelve el JSON pedido.")
                ],
                modelo_id=modelo
            )
        except Exception as e:
            logger.warning("Error de LLM en analista_normativo: %s", e)
            return {"error": str(e)}

        try:
            data = json.loads(response_text)
            return {"result": data}
        except Exception as e:
            logger.warning("Error parseando JSON del analista: %s", e)
            return {"error": str(e), "raw": response_text}
