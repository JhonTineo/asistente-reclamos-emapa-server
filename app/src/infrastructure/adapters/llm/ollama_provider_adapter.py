import logging
from typing import Any

import httpx
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage

from app.src.application.ports.provider_port import PuertoProveedorLLM, MensajeLLM
from app.src.infrastructure.system.hardware import hardware_apto_para_local

logger = logging.getLogger("tools.llm.ollama")

MAX_TOKENS_RESPUESTA = 1500


def es_modelo_de_embeddings(nombre: str) -> bool:
    """Los modelos de solo-embeddings (p.ej. nomic-embed-text) hacen que Ollama
    responda 400 a cualquier /api/chat. No deben ofrecerse como opción de chat
    ni registrarse en el catálogo de modelos conversacionales."""
    return "embed" in nombre.lower()


def modelos_chat_instalados(base_url: str) -> list[str]:
    """Modelos de CHAT descargados en Ollama (excluye los de embeddings).

    Se consulta en vivo y sin caché: el usuario descarga o borra modelos desde
    el frontend y el catálogo tiene que reflejarlo de inmediato. Devuelve lista
    vacía si Ollama no responde, para que el llamador degrade sin romperse."""
    try:
        r = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        r.raise_for_status()
        nombres = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:  # noqa: BLE001
        logger.warning("[Ollama] No se pudieron listar modelos en %s: %s", base_url, e)
        return []
    return [n for n in nombres if not es_modelo_de_embeddings(n)]


def _log_respuesta_cruda(etiqueta: str, modelo_id: str, response: BaseMessage) -> None:
    """Deja rastro del texto crudo que devolvió el modelo, antes de que el
    agente lo parsee. Sin esto, cuando el parseo falla solo queda el error y no
    se sabe qué escribió realmente el modelo."""
    contenido = str(response.content)
    meta = response.response_metadata or {}
    logger.info(
        "[Ollama] Respuesta %s | modelo=%s | chars=%d | done_reason=%s",
        etiqueta, modelo_id, len(contenido), meta.get("done_reason", "?"),
    )
    logger.debug("[Ollama] Contenido crudo %s:\n%s", etiqueta, contenido)


class InferenciaLocalNoDisponibleError(RuntimeError):
    """El servidor no cumple los requisitos para ofrecer inferencia LOCAL de chat."""


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
            lc_mensajes.append(HumanMessage(content=m.contenido))
    return lc_mensajes


class OllamaProviderAdapter(PuertoProveedorLLM):
    """
    Adaptador para Ollama en local.
    Verifica los requisitos de hardware antes de intentar instanciar el modelo.
    """
    def __init__(self, base_url: str, requiere_gpu: bool, min_ram_gb: float):
        self.base_url = base_url
        self.requiere_gpu = requiere_gpu
        self.min_ram_gb = min_ram_gb

    def _validar_hardware(self):
        apto, _ = hardware_apto_para_local(
            requiere_gpu=self.requiere_gpu,
            min_ram_gb=self.min_ram_gb,
        )
        if not apto:
            raise InferenciaLocalNoDisponibleError("Hardware local insuficiente para Ollama.")

    def _crear_cliente(self, modelo_id: str, temperatura: float) -> ChatOllama:
        self._validar_hardware()
        return ChatOllama(
            model=modelo_id,
            base_url=self.base_url,
            temperature=temperatura,
            max_retries=2,
            # Techo de seguridad equivalente a max_tokens: evita que una
            # generación descarrilada ocupe la GPU/CPU indefinidamente.
            num_predict=MAX_TOKENS_RESPUESTA,
        )

    def generar_texto(self, mensajes: list[MensajeLLM], modelo_id: str, temperatura: float = 0.0) -> str:
        llm = self._crear_cliente(modelo_id, temperatura)
        lc_mensajes = _convertir_mensajes(mensajes)

        logger.info(f"[Ollama] Generando texto con modelo: {modelo_id}")
        response = llm.invoke(lc_mensajes)
        _log_respuesta_cruda("texto", modelo_id, response)
        return str(response.content)

    def generar_json(self, mensajes: list[MensajeLLM], modelo_id: str, esquema: dict[str, Any] | None = None, temperatura: float = 0.0) -> str:
        # NO se usa bind(format="json") por el mismo motivo que en el adaptador
        # OpenAI-compat: fuerza un objeto JSON de nivel superior mientras los
        # prompts de los agentes piden una lista, y el modelo acaba generando
        # relleno hasta agotar el presupuesto de tokens. El _parse() de cada
        # agente extrae el JSON por regex y tolera texto alrededor.
        llm = self._crear_cliente(modelo_id, temperatura)
        lc_mensajes = _convertir_mensajes(mensajes)

        logger.info(f"[Ollama] Generando JSON con modelo: {modelo_id}")
        response = llm.invoke(lc_mensajes)
        _log_respuesta_cruda("json", modelo_id, response)
        return str(response.content)
