from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    
    # --- Proveedores de LLM externo (compatibles con la API de OpenAI) ---
    # Las API keys aqui son solo un FALLBACK opcional (para pruebas locales o
    # backend-only). El frontend puede enviar su propia key por header
    # X-LLM-Api-Key en cada peticion. Los *_models son el catalogo que se
    # expone al frontend; no requieren key para listarse.

    # OpenCode
    opencode_go_api_key: str = "local-dev"
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"

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

    
    # --- Requisitos de hardware para habilitar inferencia LOCAL (chat) ---
    # No aplica a los embeddings (mucho más livianos, siempre corren en Ollama
    # local). Ajustables por env sin tocar código, p.ej. en un VPS con GPU.
    ollama_base_url: str = "http://ollama:11434"
    ollama_requiere_gpu: bool = True
    ollama_min_ram_gb: float = 8.0
    ollama_embedding_model: str = "nomic-embed-text"



    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection_name: str = "sunass_reglamento"


    timeout_seconds: int = 60
    max_retries: int = 2

    emapa_api_base_url: str = "https://comercial.emapasanmartin.com:8889/sysco-comercial/backend"
    emapa_access_token: str = ""



settings = Settings()
