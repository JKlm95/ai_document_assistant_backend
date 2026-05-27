from app.embeddings.base import EmbeddingProvider, UnsupportedEmbeddingProviderError
from app.embeddings.providers.local import LocalEmbeddingProvider
from app.embeddings.providers.mock import MockEmbeddingProvider
from app.embeddings.providers.openai import OpenAIEmbeddingProvider


class EmbeddingProviderRegistry:
    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        dimensions: int,
        openai_api_key: str | None,
    ) -> None:
        self._provider_name = provider_name.lower()
        self._model_name = model_name
        self._dimensions = dimensions
        self._openai_api_key = openai_api_key

    def get_provider(self) -> EmbeddingProvider:
        if self._provider_name == "mock":
            return MockEmbeddingProvider(
                model_name=self._model_name,
                dimensions=self._dimensions,
            )
        if self._provider_name == "openai":
            return OpenAIEmbeddingProvider(
                model_name=self._model_name,
                dimensions=self._dimensions,
                api_key=self._openai_api_key,
            )
        if self._provider_name in {"local", "ollama"}:
            return LocalEmbeddingProvider(
                model_name=self._model_name,
                dimensions=self._dimensions,
            )
        raise UnsupportedEmbeddingProviderError(
            f"Unsupported embedding provider: {self._provider_name}"
        )
