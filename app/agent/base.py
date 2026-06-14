from abc import ABC, abstractmethod
from app.core.llm import get_llm
from app.tools.registry import ToolRegistry


class Agent(ABC):
    def __init__(self, model: str | None = None):
        self.model = model
        self.llm = get_llm(model=model)

    @property
    @abstractmethod
    def role(self) -> str:
        pass

    @abstractmethod
    def run(self, input_data: dict) -> dict:
        pass
