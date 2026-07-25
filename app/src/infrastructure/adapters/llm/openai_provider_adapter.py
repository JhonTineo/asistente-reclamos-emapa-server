import logging
from typing import Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from pydantic import SecretStr

from app.src.application.ports.provider_port import PuertoProveedorLLM, MensajeLLM

logger = logging.getLogger("tools.llm.openai_compat")

MAX_TOKENS_RESPUESTA = 1500


def _log_respuesta_cruda(etiqueta: str, modelo_id: str, response: BaseMessage) -> None:
    """Deja rastro del texto crudo que devolvió el modelo, antes de que el
    agente lo parsee. Sin esto, cuando el parseo falla solo queda el error y no
    se sabe qué escribió realmente el modelo."""
    contenido = str(response.content)
    meta = response.response_metadata or {}
    logger.info(
        "[OpenAI Compat] Respuesta %s | modelo=%s | chars=%d | finish_reason=%s | uso=%s",
        etiqueta, modelo_id, len(contenido),
        meta.get("finish_reason", "?"), meta.get("token_usage", {}),
    )
    logger.debug("[OpenAI Compat] Contenido crudo %s:\n%s", etiqueta, contenido)


def _convertir_mensajes(mensajes: list[MensajeLLM]) -> list[BaseMessage]:
    lc_mensajes = []
    for m in mensajes:
        if m.rol == "system":
            lc_mensajes.append(SystemMessage(content=m.contenido))
        elif m.rol == "user":
            lc_mensajes.append(HumanMessage(content=m.contenido))
        elif m.rol == "assistant":
            lc_mensajes.append(AIMessage(content=m.contenido))
        else:
            # Fallback
            lc_mensajes.append(HumanMessage(content=m.contenido))
    return lc_mensajes


class OpenAiCompatProviderAdapter(PuertoProveedorLLM):
    """
    Adaptador para cualquier proveedor que sea compatible con la API de OpenAI.
    Esto incluye OpenAI, OpenRouter, y Gemini (usando su base_url de OpenAI compat).
    """
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def _crear_cliente(self, modelo_id: str, temperatura: float) -> ChatOpenAI:
        from app.src.infrastructure.config.llm_context import get_llm_ctx
        ctx = get_llm_ctx()
        
        # Si el usuario mandó una API key explícitamente, la usamos sobre la del sistema.
        api_key = ctx.get("api_key") or self.api_key
        
        logger.info(
            "[OpenAI Compat] _crear_cliente | base_url=%s | modelo=%s | api_key=%s",
            self.base_url, modelo_id,
            f"{api_key[:8]}…" if api_key else "(vacía)",
        )
        
        return ChatOpenAI(
            model=modelo_id,
            api_key=SecretStr(api_key),
            base_url=self.base_url,
            temperature=temperatura,
            max_retries=2,
            request_timeout=60,  # 60s en vez del default de 600s
            # Techo de seguridad: sin él, una generación descarrilada corre hasta
            # el límite del modelo (16k tokens ≈ 3 min y ~1 centavo por llamada).
            # Las salidas de los agentes (objetivos, dictamen, conclusión) no
            # pasan de unos cientos de tokens.
            max_tokens=MAX_TOKENS_RESPUESTA,
        )

    def generar_texto(self, mensajes: list[MensajeLLM], modelo_id: str, temperatura: float = 0.0) -> str:
        llm = self._crear_cliente(modelo_id, temperatura)
        lc_mensajes = _convertir_mensajes(mensajes)
        
        logger.info(f"[OpenAI Compat] Generando texto con modelo: {modelo_id}")
        response = llm.invoke(lc_mensajes)
        _log_respuesta_cruda("texto", modelo_id, response)

        # response es un AIMessage
        return str(response.content)

    def generar_json(self, mensajes: list[MensajeLLM], modelo_id: str, esquema: dict[str, Any] | None = None, temperatura: float = 0.0) -> str:
        # NO se usa response_format={"type": "json_object"}: ese modo obliga a que
        # la respuesta sea un objeto JSON de nivel superior, pero los prompts de
        # los agentes piden una LISTA (`[{...}, {...}]`). Ese conflicto hacía que
        # el modelo generase sin parar hasta agotar max_tokens, devolviendo un
        # JSON truncado ("Could not parse response content as the length limit
        # was reached"). El _parse() de cada agente ya extrae el JSON por regex y
        # tolera texto alrededor, así que basta con pedirlo en el prompt.
        llm = self._crear_cliente(modelo_id, temperatura)
        lc_mensajes = _convertir_mensajes(mensajes)

        logger.info(f"[OpenAI Compat] Generando JSON con modelo: {modelo_id}")
        response = llm.invoke(lc_mensajes)
        _log_respuesta_cruda("json", modelo_id, response)

        return str(response.content)
