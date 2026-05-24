from typing import Protocol

from app.chunking.models import ChunkResult


class ChunkingStrategy(Protocol):
    def chunk(self, text: str) -> list[ChunkResult]:
        raise NotImplementedError
