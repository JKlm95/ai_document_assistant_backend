from app.llm.base import LLMProviderUnavailableError
from app.llm.models import LLMResult


class OpenAILLMProvider:
    provider_name = "openai"

    def __init__(self, *, model_name: str, api_key: str | None) -> None:
        self.model_name = model_name
        self._api_key = api_key

    async def generate_answer(self, *, prompt: str, question: str, context: str) -> LLMResult:
        if not self._api_key:
            raise LLMProviderUnavailableError("OpenAI API key is not configured")
        raise LLMProviderUnavailableError("OpenAI answer generation is not implemented yet")
