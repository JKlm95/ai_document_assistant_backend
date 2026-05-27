from app.embeddings.base import EmbeddingProviderUnavailableError
from app.embeddings.models import EmbeddingResult


class LocalEmbeddingProvider:
    provider_name = "local"

    def __init__(self, *, model_name: str, dimensions: int) -> None:
        self.model_name = model_name
        self.dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        raise EmbeddingProviderUnavailableError("Local embedding provider is not implemented yet")
