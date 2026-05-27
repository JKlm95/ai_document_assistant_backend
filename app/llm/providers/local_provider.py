from app.llm.base import LLMProviderUnavailableError
from app.llm.models import LLMResult


class LocalLLMProvider:
    provider_name = "local"

    def __init__(self, *, model_name: str) -> None:
        self.model_name = model_name

    async def generate_answer(self, *, prompt: str, question: str, context: str) -> LLMResult:
        raise LLMProviderUnavailableError("Local LLM provider is not implemented yet")
