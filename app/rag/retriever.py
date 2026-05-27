from uuid import UUID

from app.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderError,
    InvalidEmbeddingDimensionsError,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.rag.citations import build_source_reference
from app.rag.context_builder import ContextBuilder
from app.rag.models import RetrievalResponse, RetrievalResult
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository


class ProjectRetriever:
    def __init__(
        self,
        *,
        project_repository: ProjectRepository,
        document_repository: DocumentRepository,
        embedding_provider: EmbeddingProvider,
        embedding_dimensions: int,
        context_builder: ContextBuilder,
        default_limit: int,
        max_limit: int,
    ) -> None:
        self._project_repository = project_repository
        self._document_repository = document_repository
        self._embedding_provider = embedding_provider
        self._embedding_dimensions = embedding_dimensions
        self._context_builder = context_builder
        self._default_limit = default_limit
        self._max_limit = max_limit

    async def search_project(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        query: str,
        limit: int | None,
        include_context: bool,
    ) -> RetrievalResponse:
        project = await self._project_repository.get_by_id(project_id)
        if project is None or project.user_id != owner_id or project.is_archived:
            raise ProjectNotFoundError

        effective_limit = self._normalize_limit(limit)
        query_embedding = (await self._embedding_provider.embed_texts([query]))[0]
        if query_embedding.dimensions != self._embedding_dimensions:
            raise InvalidEmbeddingDimensionsError(
                f"Expected {self._embedding_dimensions}, got {query_embedding.dimensions}"
            )

        matches = await self._document_repository.search_similar_chunks_for_project(
            owner_id=owner_id,
            project_id=project_id,
            query_vector=query_embedding.vector,
            limit=effective_limit,
        )
        results = _build_results(matches)
        context = self._context_builder.build_context(results) if include_context else None
        return RetrievalResponse(
            query=query,
            project_id=project_id,
            results=results,
            context=context,
            citations=[result.source_reference for result in results],
        )

    def _normalize_limit(self, limit: int | None) -> int:
        requested_limit = limit or self._default_limit
        return min(max(1, requested_limit), self._max_limit)


def _build_results(
    matches: list[tuple[DocumentChunk, Document, float]],
) -> list[RetrievalResult]:
    results: list[RetrievalResult] = []
    seen_chunk_ids: set[UUID] = set()
    for chunk, document, similarity_score in matches:
        if chunk.id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk.id)
        source_reference = build_source_reference(
            index=len(results) + 1,
            document=document,
            chunk=chunk,
        )
        results.append(
            RetrievalResult(
                chunk_id=chunk.id,
                document_id=document.id,
                document_title=document.title,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                similarity_score=similarity_score,
                source_reference=source_reference,
                metadata={
                    "source_url": document.source_url,
                    "language": document.language,
                    "document_type": document.document_type,
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                    "page_number": None,
                },
            )
        )
    return results


class ProjectNotFoundError(Exception):
    """Raised when a project does not exist or is not owned by the user."""


__all__ = [
    "EmbeddingProviderError",
    "InvalidEmbeddingDimensionsError",
    "ProjectNotFoundError",
    "ProjectRetriever",
]
