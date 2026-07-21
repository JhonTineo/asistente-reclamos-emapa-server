from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    opencode_go_api_key: str = "local-dev"
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"

    # --- Proveedores de LLM externo (compatibles con la API de OpenAI) ---
    # Las API keys aqui son solo un FALLBACK opcional (para pruebas locales o
    # backend-only). El frontend puede enviar su propia key por header
    # X-LLM-Api-Key en cada peticion. Los *_models son el catalogo que se
    # expone al frontend; no requieren key para listarse.

    # OpenRouter
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: str = "openai/gpt-oss-20b:free,google/gemma-4-31b-it:free,openai/gpt-4o-mini"

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_models: str = "gpt-4o-mini,gpt-4o"

    # Google Gemini (via su endpoint compatible con OpenAI)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_models: str = "gemini-2.0-flash,gemini-1.5-flash"

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
