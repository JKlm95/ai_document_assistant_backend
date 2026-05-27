from typing import Protocol

from app.embeddings.models import EmbeddingResult


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str
    dimensions: int

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        raise NotImplementedError


class EmbeddingProviderError(Exception):
    """Base class for embedding provider errors."""


class EmbeddingProviderUnavailableError(EmbeddingProviderError):
    """Raised when a configured provider cannot be used."""


class UnsupportedEmbeddingProviderError(EmbeddingProviderError):
    """Raised when provider registry does not support a provider key."""


class InvalidEmbeddingDimensionsError(EmbeddingProviderError):
    """Raised when a provider returns unexpected vector dimensions."""
