import logging
from typing import Any
from app.src.application.ports.model_port import PuertoCatalogoModelos
from app.src.application.ports.provider_port import PuertoProveedorLLM, MensajeLLM

logger = logging.getLogger("services.llm_router")

# Modelo usado cuando el llamador (frontend) no especifica ninguno.
#
# El prefijo `openai/` NO es decorativo: el catálogo enruta por el id completo.
# `openai/gpt-4o-mini` -> proveedor `openrouter`; `gpt-4o-mini` (sin prefijo)
# -> proveedor `openai`, que es otra cuenta y otra cuota. Quitar el prefijo
# cambia de proveedor en silencio y el síntoma es un 429 insufficient_quota.
#
# Vive acá, y no repetido en cada agente, para que un cambio de modelo no deje
# a ninguno desincronizado.
MODELO_EXTERNO_DEFAULT = "openai/gpt-4o-mini"


class LlmRouterService:
    """
    Orquestador principal (OmniRouter interno) para interactuar con los LLMs.
    Desacopla a los Agentes de los proveedores específicos.
    """
    def __init__(
        self,
        catalogo: PuertoCatalogoModelos,
        providers: dict[str, PuertoProveedorLLM]
    ):
        """
        :param catalogo: Puerto para consultar modelos disponibles.
        :param providers: Diccionario de adaptadores de proveedores inyectados 
                          (ej. {"openai": OpenAiAdapter, "openrouter": ...})
        """
        self.catalogo = catalogo
        self.providers = providers

    def _ejecutar_con_fallback(
        self,
        modelo_id: str,
        operacion: str,
        mensajes: list[MensajeLLM],
        esquema: dict[str, Any] | None = None,
        temperatura: float = 0.0
    ) -> str:
        
        modelo = self.catalogo.obtener_modelo(modelo_id)
        if not modelo:
            # Fallback generico si el modelo no está en catálogo: intentar
            # usar el primer proveedor disponible asumiendo que lo soporta.
            logger.warning(f"[LlmRouter] Modelo '{modelo_id}' no encontrado en catálogo. Intentando fallback genérico.")
            provider_ids = list(self.providers.keys())
        else:
            provider_ids = self.catalogo.proveedores_para(modelo_id)
            
        if not provider_ids:
            raise RuntimeError(f"No hay proveedores configurados para el modelo {modelo_id}")

        last_error = None
        for pid in provider_ids:
            if pid not in self.providers:
                logger.warning(f"[LlmRouter] El catálogo sugiere el proveedor '{pid}' pero no está inyectado/configurado.")
                continue

            provider = self.providers[pid]
            try:
                if operacion == "texto":
                    return provider.generar_texto(mensajes, modelo_id, temperatura)
                elif operacion == "json":
                    return provider.generar_json(mensajes, modelo_id, esquema, temperatura)
            except Exception as e:
                logger.error(f"[LlmRouter] Error con proveedor '{pid}' para modelo '{modelo_id}': {e}")
                last_error = e
                # Continua con el siguiente proveedor en la lista (Fallback)

        raise RuntimeError(f"Todos los proveedores fallaron para el modelo {modelo_id}. Último error: {last_error}")


    def generar_texto(self, mensajes: list[MensajeLLM], modelo_id: str, temperatura: float = 0.0) -> str:
        """Genera texto delegando al mejor proveedor disponible."""
        return self._ejecutar_con_fallback(modelo_id, "texto", mensajes, temperatura=temperatura)

    def generar_json(self, mensajes: list[MensajeLLM], modelo_id: str, esquema: dict[str, Any] | None = None, temperatura: float = 0.0) -> str:
        """Genera JSON delegando al mejor proveedor disponible."""
        return self._ejecutar_con_fallback(modelo_id, "json", mensajes, esquema=esquema, temperatura=temperatura)
