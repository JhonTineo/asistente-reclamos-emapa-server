from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    opencode_go_api_key: str = "local-dev"
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"
    llm_model: str = "deepseek-v4-flash"

    ollama_base_url: str = "http://ollama:11434"
    ollama_generator_model: str = "llama3.2:3b"

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection_name: str = "sunass_reglamento"
    embedding_model: str = "BAAI/bge-m3"

    ollama_embedding_model: str = "nomic-embed-text"

    timeout_seconds: int = 60
    max_retries: int = 2

    emapa_api_base_url: str = "https://comercial.emapasanmartin.com:8889/sysco-comercial/backend"
    emapa_access_token: str = ""



settings = Settings()
