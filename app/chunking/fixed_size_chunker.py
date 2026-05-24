import re

from app.chunking.models import ChunkResult


class FixedSizeChunkingStrategy:
    def __init__(self, *, chunk_size_chars: int, chunk_overlap_chars: int) -> None:
        if chunk_size_chars <= 0:
            raise ValueError("chunk_size_chars must be greater than zero")
        if chunk_overlap_chars < 0:
            raise ValueError("chunk_overlap_chars cannot be negative")
        if chunk_overlap_chars >= chunk_size_chars:
            raise ValueError("chunk_overlap_chars must be smaller than chunk_size_chars")

        self._chunk_size_chars = chunk_size_chars
        self._chunk_overlap_chars = chunk_overlap_chars

    def chunk(self, text: str) -> list[ChunkResult]:
        normalized_text = _normalize_whitespace(text)
        if not normalized_text:
            return []

        chunks: list[ChunkResult] = []
        start_offset = 0
        step = self._chunk_size_chars - self._chunk_overlap_chars

        while start_offset < len(normalized_text):
            end_offset = min(start_offset + self._chunk_size_chars, len(normalized_text))
            chunk_text = normalized_text[start_offset:end_offset].strip()
            if chunk_text:
                chunks.append(
                    ChunkResult(
                        chunk_index=len(chunks),
                        text=chunk_text,
                        char_count=len(chunk_text),
                        token_count_estimate=_estimate_token_count(chunk_text),
                        start_offset=start_offset,
                        end_offset=end_offset,
                    )
                )
            if end_offset == len(normalized_text):
                break
            start_offset += step

        return chunks


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _estimate_token_count(text: str) -> int:
    return max(1, (len(text) + 3) // 4)
