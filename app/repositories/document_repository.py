from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, ProjectDocument


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

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, document: Document) -> None:
        await self._session.refresh(document)
