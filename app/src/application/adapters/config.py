from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    opencode_go_api_key: str = "local-dev"
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"

    # --- OpenRouter (LLM externo compatible con la API de OpenAI) ---
    # Si openrouter_api_key esta vacio, no se expone ningun modelo externo y el
    # comportamiento queda identico al de solo-Ollama.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Lista separada por comas de ids de modelos de OpenRouter a mostrar en el
    # frontend, p.ej. "openai/gpt-4o-mini,anthropic/claude-3.5-sonnet".
    openrouter_models: str = "openai/gpt-4o-mini"

    ollama_base_url: str = "http://ollama:11434"

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection_name: str = "sunass_reglamento"

    # Modelo de EMBEDDINGS (no de chat): a diferencia del modelo de chat, este
    # sí necesita ser fijo, porque el índice de Qdrant se construyó con él;
    # cambiarlo sin reindexar rompe la búsqueda semántica.
    ollama_embedding_model: str = "nomic-embed-text"

    timeout_seconds: int = 60
    max_retries: int = 2

    emapa_api_base_url: str = "https://comercial.emapasanmartin.com:8889/sysco-comercial/backend"
    emapa_access_token: str = ""



settings = Settings()
