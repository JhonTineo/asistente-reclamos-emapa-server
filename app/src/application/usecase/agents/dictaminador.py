import json
import logging
from app.src.application.ports.provider_port import MensajeLLM
from app.src.application.services.llm.llm_router_service import LlmRouterService, MODELO_EXTERNO_DEFAULT

logger = logging.getLogger("agent.dictaminador")

class DictaminadorAgent:

    def __init__(self, llm_router: LlmRouterService, model: str | None = None):
        self.llm_router = llm_router
        self.model_id = model or MODELO_EXTERNO_DEFAULT

    def run(
        self,
        detalle: str,
        clasificacion: str,
        evidencias: list | dict | str,
        articulos: str,
        resumen_servicio: str
    ) -> dict:

        if isinstance(evidencias, (dict, list)):
            texto_evidencias = json.dumps(
                evidencias,
                ensure_ascii=False,
                indent=2,
            )
        else:
            texto_evidencias = str(evidencias)

        system = (
            "Eres un especialista jurídico en regulación SUNASS.\n"
            "Debes analizar:\n"
            "1. Reclamo.\n"
            "2. Evidencias.\n"
            "3. Artículos normativos.\n"
            "4. Resumen analítico de servicio anual brindado por EMAPA.\n\n"
            "No utilices conocimiento externo.\n"
            "Responde únicamente JSON.\n"
            "Formato:\n"
            "{\n"
            '    "clasificacion":"",\n'
            '    "procede":true,\n'
            '    "nivel_confianza":0.0,\n'
            '    "articulos_aplicables":[],\n'
            '    "fundamento":"",\n'
            '    "requiere_revision_humana":false\n'
            "}"
        )

        human = (
            f"RECLAMO\n{detalle}\n\n"
            f"CLASIFICACIÓN DE RECLAMO\n{clasificacion}\n\n"
            f"EVIDENCIAS\n{texto_evidencias}\n\n"
            f"ARTICULOS\n{articulos}\n\n"
            f"RESUMEN ANALÍTICO DE SERVICIO ANUAL BRINDADO POR EMAPA\n{resumen_servicio}"
        )

        try:
            response_text = self.llm_router.generar_json(
                mensajes=[
                    MensajeLLM(rol="system", contenido=system),
                    MensajeLLM(rol="user", contenido=human)
                ],
                modelo_id=self.model_id
            )
            return json.loads(response_text)
        except Exception as e:
            logger.warning("[DICTAMINADOR] Error: %s", e)
            return {"error": str(e)}