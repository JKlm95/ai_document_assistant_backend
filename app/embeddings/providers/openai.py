from app.embeddings.base import EmbeddingProviderUnavailableError
from app.embeddings.models import EmbeddingResult


class OpenAIEmbeddingProvider:
    provider_name = "openai"

    def __init__(self, *, model_name: str, dimensions: int, api_key: str | None) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._api_key = api_key

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not self._api_key:
            raise EmbeddingProviderUnavailableError("OpenAI API key is not configured")
        raise EmbeddingProviderUnavailableError("OpenAI embedding calls are not implemented yet")
