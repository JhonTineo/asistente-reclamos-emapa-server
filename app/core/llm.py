from langchain_openai import ChatOpenAI
from app.core.config import settings

def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.opencode_go_base_url,
        api_key=settings.opencode_go_api_key,
        temperature=0.2,
    )
