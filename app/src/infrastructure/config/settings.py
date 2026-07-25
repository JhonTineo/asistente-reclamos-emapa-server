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

    # Los cinco proveedores del combo externo. Todos exponen una API compatible
    # con OpenAI, así que los atiende el mismo OpenAiCompatProviderAdapter: lo
    # único que cambia es base_url + api_key. El ORDEN del proxy no se define
    # aquí sino en deps.PROVEEDORES_EXTERNOS.

    # OpenRouter — agregador; da acceso a modelos :free y a gpt-4o-mini barato.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: str = "openai/gpt-4o-mini,openai/gpt-oss-20b:free"

    # Groq — ~15M tok/mes, latencia muy baja.
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_models: str = "llama-3.3-70b-versatile,openai/gpt-oss-20b"

    # Cloudflare Workers AI — la URL lleva el account id, por eso se arma en
    # deps a partir de cloudflare_account_id. Gratis ~10K Neurons/día, que son
    # del orden de 150 respuestas LLM diarias: sirve de red de seguridad, no
    # como proveedor principal.
    cloudflare_api_key: str = ""
    cloudflare_account_id: str = ""
    cloudflare_models: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast,@cf/meta/llama-3.1-8b-instruct-fp8"

    # Mistral — free "Experiment"
    mistral_api_key: str = ""
    mistral_base_url: str = "https://api.mistral.ai/v1"
    mistral_models: str = "mistral-small-latest,mistral-large-latest"

    # Gemini — ~1,500 req/día en Flash
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_models: str = "gemini-2.0-flash,gemini-1.5-flash"
    

    # OpenCode Zen — modelos free sin tope publicado (limitado por rate).
    opencode_api_key: str = ""
    opencode_base_url: str = "https://opencode.ai/zen/v1"
    opencode_models: str = "deepseek-v4-flash-free,nemotron-3-ultra-free"

    # GitHub Models — Azure AI gratuito para cuentas GitHub
    githubmodels_api_key: str = ""
    githubmodels_base_url: str = "https://models.inference.ai.azure.com"
    githubmodels_models: str = "Llama-3.3-70B-Instruct,Mistral-small,Phi-3-mini-4k-instruct"

    # Plugsky — proveedor asiático con alta cuota gratuita y modelos openai-compat
    plugsky_api_key: str = ""
    plugsky_base_url: str = "https://api.plugsky.com/v1"
    plugsky_models: str = "gpt-4o-mini,claude-3-haiku-20240307"

    



#Provedores sin capa gratuita pero con bajo precio

    # DeepSeek — muy barato oficial ($0.14 / 1M tokens)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_models: str = "deepseek-chat,deepseek-reasoner"

    # SiliconFlow — alternativa extremadamente barata/gratuita en China
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_models: str = "Qwen/Qwen2.5-7B-Instruct,deepseek-ai/DeepSeek-V3"

    # Cerebras — ~30M tok/mes. Su ToS concede uso "personal or business",
    # el más claro de los cinco para un despliegue corporativo.
    cerebras_api_key: str = ""
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_models: str = "zai-glm-4.7,gpt-oss-120b"



#Infraestructura de inferencia LOCAL (Ollama) — 
    # --- Requisitos de hardware para habilitar inferencia LOCAL (chat) ---
    # No aplica a los embeddings
    ollama_base_url: str = "http://ollama:11434"
    ollama_requiere_gpu: bool = True
    ollama_min_ram_gb: float = 8.0
    ollama_embedding_model: str = "nomic-embed-text"


    # --- Configuración de tiempo de espera y reintentos ---
    timeout_seconds: int = 60
    max_retries: int = 2


    # --- Configuración de la API de EMAPA ---
    emapa_api_base_url: str = "https://comercial.emapasanmartin.com:8889/sysco-comercial/backend"
    emapa_access_token: str = ""


    # --- Configuración de la API de Qdrant ---
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection_name: str = "sunass_reglamento"



settings = Settings()
