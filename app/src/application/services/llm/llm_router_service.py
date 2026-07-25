import logging
from typing import Any
from app.src.application.ports.model_port import PuertoCatalogoModelos
from app.src.application.ports.provider_port import PuertoProveedorLLM, MensajeLLM

logger = logging.getLogger("services.llm_router")

# Sentinela: "sin preferencia de modelo, usa lo mejor disponible". Es lo que
# usan los agentes por defecto cuando el frontend no especifica `modelo`.
#
# Con un id FIJO (p.ej. "openai/gpt-4o-mini") el fallback entre proveedores no
# cruza proveedores distintos: ese id solo lo declara OpenRouter en el
# catálogo, así que si OpenRouter falla, el router lanza error de inmediato en
# vez de probar Groq/Cloudflare/etc, aunque estén configurados en el combo
# (cada proveedor usa su propio nombre de modelo: "llama-3.3-70b-versatile" en
# Groq no es "openai/gpt-4o-mini"). Con MODELO_AUTO, el router recorre
# orden_proveedores probando en cada uno SU modelo preferido — así el proxy sí
# cruza proveedores con nomenclaturas distintas.
MODELO_AUTO = "auto"
MODELO_EXTERNO_DEFAULT = MODELO_AUTO


class LlmRouterService:
    """
    Orquestador principal (OmniRouter interno) para interactuar con los LLMs.
    Desacopla a los Agentes de los proveedores específicos.
    """
    def __init__(
        self,
        catalogo: PuertoCatalogoModelos,
        providers: dict[str, PuertoProveedorLLM],
        orden_proveedores: list[str] | None = None,
    ):
        """
        :param catalogo: Puerto para consultar modelos disponibles.
        :param providers: Diccionario de adaptadores de proveedores inyectados
                          (ej. {"openai": OpenAiAdapter, "openrouter": ...})
        :param orden_proveedores: Proveedores candidatos, en orden de intento.
            Lo fija el composition root según el modo que eligió el usuario
            (externo con proxy, o local sin proxy). El router NO decide el modo:
            solo respeta la lista que recibe. Si es None, se usan todos los
            proveedores inyectados (comportamiento histórico).
        """
        self.catalogo = catalogo
        self.providers = providers
        self.orden_proveedores = orden_proveedores or list(providers.keys())

    def _ejecutar_con_fallback(
        self,
        modelo_id: str,
        operacion: str,
        mensajes: list[MensajeLLM],
        esquema: dict[str, Any] | None = None,
        temperatura: float = 0.0
    ) -> str:
        if modelo_id == MODELO_AUTO:
            return self._ejecutar_auto(operacion, mensajes, esquema, temperatura)

        # `orden_proveedores` acota el modo (externo / local). El catálogo acota
        # quién declara este modelo estáticamente.
        soportan = self.catalogo.proveedores_para(modelo_id)
        provider_ids = []
        
        if self.orden_proveedores:
            # Siempre intentar el primer proveedor de la lista, ya que suele ser 
            # la elección explícita del usuario y podría tener el modelo por descubrimiento dinámico.
            provider_ids.append(self.orden_proveedores[0])
            
        if soportan:
            for p in self.orden_proveedores:
                if p in soportan and p not in provider_ids:
                    provider_ids.append(p)
        else:
            # Modelo no declarado en el catálogo (p.ej. uno de Ollama recién
            # descargado, o uno dinámico puro). Se intentan los proveedores del modo.
            logger.warning(
                "[LlmRouter] Modelo '%s' no está en el catálogo; se intentará con %s",
                modelo_id, self.orden_proveedores,
            )
            for p in self.orden_proveedores:
                if p not in provider_ids:
                    provider_ids.append(p)

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

        if last_error:
            # Relanzamos la excepción original para que los exception_handlers de FastAPI 
            # (ej. 402 Payment Required, 401 Auth) la procesen correctamente en vez de ser un 500
            raise last_error
            
        raise RuntimeError(f"Todos los proveedores fallaron para el modelo {modelo_id}.")

    def _ejecutar_auto(
        self,
        operacion: str,
        mensajes: list[MensajeLLM],
        esquema: dict[str, Any] | None,
        temperatura: float,
    ) -> str:
        """Recorre orden_proveedores probando, en CADA proveedor, su propio
        modelo preferido (el primero de su lista configurada) — no un id fijo.
        Es lo que permite que el proxy cruce proveedores aunque cada uno llame
        distinto al mismo tipo de modelo."""
        last_error: Exception | None = None
        intentos = 0
        for pid in self.orden_proveedores:
            if pid not in self.providers:
                continue
            modelos = self.catalogo.modelos_para_proveedor(pid)
            if not modelos:
                logger.warning(
                    "[LlmRouter] (auto) Proveedor '%s' sin modelos configurados; se omite.", pid,
                )
                continue

            modelo_id = modelos[0]
            intentos += 1
            provider = self.providers[pid]
            try:
                if operacion == "texto":
                    return provider.generar_texto(mensajes, modelo_id, temperatura)
                elif operacion == "json":
                    return provider.generar_json(mensajes, modelo_id, esquema, temperatura)
            except Exception as e:
                logger.error(
                    "[LlmRouter] (auto) Error con proveedor '%s' modelo '%s': %s", pid, modelo_id, e,
                )
                last_error = e

        if intentos == 0:
            raise RuntimeError(
                f"Ningún proveedor de {self.orden_proveedores} tiene modelos configurados."
            )
        raise RuntimeError(
            f"Todos los proveedores del combo {self.orden_proveedores} fallaron en modo auto. "
            f"Último error: {last_error}"
        )

    def generar_texto(self, mensajes: list[MensajeLLM], modelo_id: str, temperatura: float = 0.0) -> str:
        """Genera texto delegando al mejor proveedor disponible."""
        return self._ejecutar_con_fallback(modelo_id, "texto", mensajes, temperatura=temperatura)

    def generar_json(self, mensajes: list[MensajeLLM], modelo_id: str, esquema: dict[str, Any] | None = None, temperatura: float = 0.0) -> str:
        """Genera JSON delegando al mejor proveedor disponible."""
        return self._ejecutar_con_fallback(modelo_id, "json", mensajes, esquema=esquema, temperatura=temperatura)
