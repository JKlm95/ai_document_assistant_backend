from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkResult:
    chunk_index: int
    text: str
    char_count: int
    token_count_estimate: int
    start_offset: int
    end_offset: int
