from app.rag.models import RetrievalResult


class ContextBuilder:
    def __init__(self, *, max_chars: int) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be greater than zero")
        self._max_chars = max_chars

    def build_context(self, results: list[RetrievalResult]) -> str:
        context_parts: list[str] = []
        used_chars = 0
        seen_chunk_ids: set[str] = set()

        for result in results:
            chunk_key = str(result.chunk_id)
            if chunk_key in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_key)

            part = (
                f"{result.source_reference.citation_id} "
                f"{result.document_title} / chunk {result.chunk_index}\n"
                f"{result.text.strip()}"
            )
            separator = "\n\n---\n\n" if context_parts else ""
            remaining_chars = self._max_chars - used_chars - len(separator)
            if remaining_chars <= 0:
                break
            if len(part) > remaining_chars:
                part = part[:remaining_chars].rstrip()
            if not part:
                break

            context_parts.append(f"{separator}{part}" if separator else part)
            used_chars += len(separator) + len(part)

        return "".join(context_parts)
