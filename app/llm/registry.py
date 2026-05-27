from app.llm.base import LLMProvider, UnsupportedLLMProviderError
from app.llm.providers.local_provider import LocalLLMProvider
from app.llm.providers.mock_provider import MockLLMProvider
from app.llm.providers.openai_provider import OpenAILLMProvider


class LLMProviderRegistry:
    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        openai_api_key: str | None,
    ) -> None:
        self._provider_name = provider_name.lower()
        self._model_name = model_name
        self._openai_api_key = openai_api_key

    def get_provider(self) -> LLMProvider:
        if self._provider_name == "mock":
            return MockLLMProvider(model_name=self._model_name)
        if self._provider_name == "openai":
            return OpenAILLMProvider(
                model_name=self._model_name,
                api_key=self._openai_api_key,
            )
        if self._provider_name in {"local", "ollama"}:
            return LocalLLMProvider(model_name=self._model_name)
        raise UnsupportedLLMProviderError(f"Unsupported LLM provider: {self._provider_name}")
