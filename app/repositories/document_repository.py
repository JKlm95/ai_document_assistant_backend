from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking.models import ChunkResult
from app.models.document import (
    Document,
    DocumentClassification,
    DocumentProcessingMode,
    ProjectDocument,
)
from app.models.document_chunk import ChunkEmbeddingStatus, DocumentChunk


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        owner_id: UUID,
        title: str,
        original_filename: str,
        mime_type: str,
        file_size_bytes: int,
        storage_provider: str,
        content_hash: str | None,
        document_id: UUID | None = None,
        storage_path: str | None = None,
        file_extension: str | None = None,
        uploaded_at: datetime | None = None,
        classification: DocumentClassification = DocumentClassification.INTERNAL,
        processing_mode: DocumentProcessingMode = DocumentProcessingMode.PREFER_LOCAL,
        language: str | None = None,
        country: str | None = None,
        document_type: str | None = None,
        tags: list[str] | None = None,
        source_url: str | None = None,
        version: str | None = None,
    ) -> Document:
        document = Document(
            owner_id=owner_id,
            title=title,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            storage_provider=storage_provider,
            content_hash=content_hash,
            storage_path=storage_path,
            file_extension=file_extension,
            uploaded_at=uploaded_at,
            classification=classification,
            processing_mode=processing_mode,
            language=language,
            country=country,
            document_type=document_type,
            tags=tags,
            source_url=source_url,
            version=version,
        )
        if document_id is not None:
            document.id = document_id
        self._session.add(document)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def get_by_id(self, document_id: UUID) -> Document | None:
        return await self._session.get(Document, document_id)

    async def list_for_owner(self, *, owner_id: UUID, limit: int, offset: int) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .where(Document.owner_id == owner_id)
            .order_by(Document.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_owner(self, *, owner_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Document).where(Document.owner_id == owner_id)
        )
        return result.scalar_one()

    async def get_project_document(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectDocument | None:
        return await self._session.get(
            ProjectDocument,
            {"project_id": project_id, "document_id": document_id},
        )

    async def attach_to_project(self, *, project_id: UUID, document_id: UUID) -> ProjectDocument:
        project_document = ProjectDocument(project_id=project_id, document_id=document_id)
        self._session.add(project_document)
        await self._session.flush()
        return project_document

    async def detach_from_project(self, project_document: ProjectDocument) -> None:
        await self._session.delete(project_document)
        await self._session.flush()

    async def list_for_project(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .join(ProjectDocument, ProjectDocument.document_id == Document.id)
            .where(ProjectDocument.project_id == project_id, Document.owner_id == owner_id)
            .order_by(Document.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_project(self, *, project_id: UUID, owner_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Document)
            .join(ProjectDocument, ProjectDocument.document_id == Document.id)
            .where(ProjectDocument.project_id == project_id, Document.owner_id == owner_id)
        )
        return result.scalar_one()

    async def delete_chunks_for_document(self, *, document_id: UUID) -> None:
        await self._session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await self._session.flush()

    async def create_chunks(
        self,
        *,
        document_id: UUID,
        chunks: list[ChunkResult],
    ) -> list[DocumentChunk]:
        document_chunks = [
            DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                char_count=chunk.char_count,
                token_count_estimate=chunk.token_count_estimate,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
            )
            for chunk in chunks
        ]
        self._session.add_all(document_chunks)
        await self._session.flush()
        return document_chunks

    async def list_chunks_for_document(self, *, document_id: UUID) -> list[DocumentChunk]:
        result = await self._session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(result.scalars().all())

    async def reset_embeddings_for_document(self, *, document_id: UUID) -> None:
        chunks = await self.list_chunks_for_document(document_id=document_id)
        for chunk in chunks:
            chunk.embedding_provider = None
            chunk.embedding_model = None
            chunk.embedded_at = None
            chunk.embedding_error = None
            chunk.embedding_status = ChunkEmbeddingStatus.PENDING
            chunk.embedding_dimensions = None
            chunk.embedding_vector = None
        await self._session.flush()

    async def search_similar_chunks(
        self,
        *,
        owner_id: UUID,
        query_vector: list[float],
        limit: int,
    ) -> list[tuple[DocumentChunk, float]]:
        distance = DocumentChunk.embedding_vector.cosine_distance(query_vector)
        result = await self._session.execute(
            select(DocumentChunk, (1 - distance).label("similarity_score"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.owner_id == owner_id,
                DocumentChunk.embedding_status == ChunkEmbeddingStatus.EMBEDDED,
                DocumentChunk.embedding_vector.is_not(None),
            )
            .order_by(distance.asc())
            .limit(limit)
        )
        return [(chunk, float(score)) for chunk, score in result.all()]

    async def search_similar_chunks_for_project(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        query_vector: list[float],
        limit: int,
    ) -> list[tuple[DocumentChunk, Document, float]]:
        distance = DocumentChunk.embedding_vector.cosine_distance(query_vector)
        result = await self._session.execute(
            select(DocumentChunk, Document, (1 - distance).label("similarity_score"))
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(ProjectDocument, ProjectDocument.document_id == Document.id)
            .where(
                Document.owner_id == owner_id,
                ProjectDocument.project_id == project_id,
                DocumentChunk.embedding_status == ChunkEmbeddingStatus.EMBEDDED,
                DocumentChunk.embedding_vector.is_not(None),
            )
            .order_by(distance.asc())
            .limit(limit)
        )
        return [(chunk, document, float(score)) for chunk, document, score in result.all()]

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, document: Document) -> None:
        await self._session.refresh(document)
