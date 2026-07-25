from typing import Optional
from app.src.application.ports.model_port import PuertoCatalogoModelos, ModeloInfo

class ModelCatalogAdapter(PuertoCatalogoModelos):
    def __init__(self, provider_model_map: dict[str, list[str]]):
        """
        Inicializa el catálogo.
        :param provider_model_map: Diccionario { "provider_id": ["modelo_1", "modelo_2"] }
        """
        self._provider_model_map = provider_model_map
        
        # Invertir mapa para busquedas rapidas: modelo_id -> list[provider_id]
        self._model_providers: dict[str, list[str]] = {}
        for provider, modelos in provider_model_map.items():
            for m in modelos:
                if m not in self._model_providers:
                    self._model_providers[m] = []
                self._model_providers[m].append(provider)

    def listar_modelos(self) -> list[ModeloInfo]:
        modelos = []
        for model_id in self._model_providers.keys():
            # TODO: Hardcoded stats for now, could be loaded from config
            is_local = "ollama" in self._model_providers[model_id] or "local" in model_id.lower()
            modelos.append(ModeloInfo(
                id=model_id,
                label=model_id.title(),
                is_local=is_local
            ))
        return modelos

    def obtener_modelo(self, modelo_id: str) -> Optional[ModeloInfo]:
        if modelo_id in self._model_providers:
            is_local = "ollama" in self._model_providers[modelo_id] or "local" in modelo_id.lower()
            return ModeloInfo(id=modelo_id, label=modelo_id.title(), is_local=is_local)
        return None

    def proveedores_para(self, modelo_id: str) -> list[str]:
        return self._model_providers.get(modelo_id, [])
