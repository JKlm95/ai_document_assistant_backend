from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.embeddings.base import (
    EmbeddingProvider,
    EmbeddingProviderError,
    InvalidEmbeddingDimensionsError,
)
from app.models.document import Document, DocumentProcessingStatus
from app.models.document_chunk import ChunkEmbeddingStatus, DocumentChunk
from app.repositories.document_repository import DocumentRepository


@dataclass(frozen=True)
class EmbeddingStatusSummary:
    document: Document
    total_chunks: int
    pending_chunks: int
    embedded_chunks: int
    failed_chunks: int


@dataclass(frozen=True)
class SimilarChunkResult:
    chunk: DocumentChunk
    similarity_score: float


class DocumentEmbeddingService:
    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        embedding_provider: EmbeddingProvider,
        embedding_dimensions: int,
    ) -> None:
        self._document_repository = document_repository
        self._embedding_provider = embedding_provider
        self._embedding_dimensions = embedding_dimensions

    async def embed_document(self, *, document_id: UUID, owner_id: UUID) -> EmbeddingStatusSummary:
        document = await self._get_owned_document(document_id=document_id, owner_id=owner_id)
        chunks = await self._document_repository.list_chunks_for_document(document_id=document.id)

        await self._document_repository.reset_embeddings_for_document(document_id=document.id)
        document.processing_status = DocumentProcessingStatus.CHUNKED
        document.processing_error = None
        await self._document_repository.commit()
        await self._document_repository.refresh(document)
        chunks = await self._document_repository.list_chunks_for_document(document_id=document.id)

        embedded_count = 0
        for chunk in chunks:
            try:
                result = (await self._embedding_provider.embed_texts([chunk.text]))[0]
                if result.dimensions != self._embedding_dimensions:
                    raise InvalidEmbeddingDimensionsError(
                        f"Expected {self._embedding_dimensions}, got {result.dimensions}"
                    )
            except (EmbeddingProviderError, IndexError, Exception) as exc:
                chunk.embedding_status = ChunkEmbeddingStatus.FAILED
                chunk.embedding_error = str(exc) or exc.__class__.__name__
                chunk.embedding_provider = self._embedding_provider.provider_name
                chunk.embedding_model = self._embedding_provider.model_name
                continue

            chunk.embedding_vector = result.vector
            chunk.embedding_dimensions = result.dimensions
            chunk.embedding_provider = result.provider
            chunk.embedding_model = result.model
            chunk.embedded_at = datetime.now(UTC)
            chunk.embedding_error = None
            chunk.embedding_status = ChunkEmbeddingStatus.EMBEDDED
            embedded_count += 1

        if chunks and embedded_count == 0:
            document.processing_status = DocumentProcessingStatus.FAILED
            document.processing_error = "Embedding generation failed for all chunks"
        else:
            document.processing_status = DocumentProcessingStatus.EMBEDDED
            await self._document_repository.commit()
            await self._document_repository.refresh(document)
            document.processing_status = DocumentProcessingStatus.INDEXED
            await self._document_repository.commit()
            await self._document_repository.refresh(document)
            document.processing_status = DocumentProcessingStatus.READY

        await self._document_repository.commit()
        await self._document_repository.refresh(document)
        return await self.get_embedding_status(document_id=document.id, owner_id=owner_id)

    async def get_embedding_status(
        self, *, document_id: UUID, owner_id: UUID
    ) -> EmbeddingStatusSummary:
        document = await self._get_owned_document(document_id=document_id, owner_id=owner_id)
        chunks = await self._document_repository.list_chunks_for_document(document_id=document.id)
        return _build_status_summary(document=document, chunks=chunks)

    async def find_similar_chunks(
        self,
        *,
        owner_id: UUID,
        query: str,
        limit: int,
    ) -> list[SimilarChunkResult]:
        query_embedding = (await self._embedding_provider.embed_texts([query]))[0]
        if query_embedding.dimensions != self._embedding_dimensions:
            raise InvalidEmbeddingDimensionsError(
                f"Expected {self._embedding_dimensions}, got {query_embedding.dimensions}"
            )
        results = await self._document_repository.search_similar_chunks(
            owner_id=owner_id,
            query_vector=query_embedding.vector,
            limit=limit,
        )
        return [
            SimilarChunkResult(chunk=chunk, similarity_score=score)
            for chunk, score in results
        ]

    async def _get_owned_document(self, *, document_id: UUID, owner_id: UUID) -> Document:
        document = await self._document_repository.get_by_id(document_id)
        if document is None or document.owner_id != owner_id:
            raise DocumentNotFoundError
        return document


def _build_status_summary(
    *, document: Document, chunks: list[DocumentChunk]
) -> EmbeddingStatusSummary:
    pending_chunks = 0
    embedded_chunks = 0
    failed_chunks = 0
    for chunk in chunks:
        if chunk.embedding_status == ChunkEmbeddingStatus.PENDING:
            pending_chunks += 1
        elif chunk.embedding_status == ChunkEmbeddingStatus.EMBEDDED:
            embedded_chunks += 1
        elif chunk.embedding_status == ChunkEmbeddingStatus.FAILED:
            failed_chunks += 1

    return EmbeddingStatusSummary(
        document=document,
        total_chunks=len(chunks),
        pending_chunks=pending_chunks,
        embedded_chunks=embedded_chunks,
        failed_chunks=failed_chunks,
    )


class DocumentNotFoundError(Exception):
    """Raised when a document does not exist or is not owned by the user."""
