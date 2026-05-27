import math

from app.embeddings.models import EmbeddingResult


class MockEmbeddingProvider:
    provider_name = "mock"

    def __init__(self, *, model_name: str, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be greater than zero")
        self.model_name = model_name
        self.dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(
                vector=_text_to_vector(text, dimensions=self.dimensions),
                provider=self.provider_name,
                model=self.model_name,
            )
            for text in texts
        ]


def _text_to_vector(text: str, *, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    normalized_text = text.lower()
    for index, character in enumerate(normalized_text):
        bucket = (ord(character) + index) % dimensions
        vector[bucket] += 1.0

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]
