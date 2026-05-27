from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    provider: str
    model: str

    @property
    def dimensions(self) -> int:
        return len(self.vector)


@dataclass(frozen=True)
class SimilarChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    similarity_score: float
    embedding_provider: str | None
    embedding_model: str | None
