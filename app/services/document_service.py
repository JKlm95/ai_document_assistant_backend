from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.models.document import Document
from app.models.project import Project
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.storage.local_storage import LocalStorageService


class DocumentService:
    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        project_repository: ProjectRepository,
    ) -> None:
        self._document_repository = document_repository
        self._project_repository = project_repository

    async def create_document(
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
        document = await self._document_repository.create(
            owner_id=owner_id,
            title=title,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size_bytes=file_size_bytes,
            storage_provider=storage_provider,
            content_hash=content_hash,
            document_id=document_id,
            storage_path=storage_path,
            file_extension=file_extension,
            uploaded_at=uploaded_at,
        )
        await self._document_repository.commit()
        await self._document_repository.refresh(document)
        return document

    async def upload_document(
        self,
        *,
        owner_id: UUID,
        upload_file: UploadFile,
        storage_service: LocalStorageService,
        project_id: UUID | None,
    ) -> tuple[Document, UUID | None]:
        if project_id is not None:
            await self._get_owned_project(project_id=project_id, owner_id=owner_id)

        document_id = uuid4()
        stored_file = await storage_service.save_upload(
            upload_file=upload_file,
            owner_id=owner_id,
            document_id=document_id,
        )
        try:
            document = await self.create_document(
                owner_id=owner_id,
                title=Path(stored_file.original_filename).stem or stored_file.original_filename,
                original_filename=stored_file.original_filename,
                mime_type=stored_file.mime_type,
                file_size_bytes=stored_file.file_size_bytes,
                storage_provider="local",
                content_hash=stored_file.content_hash,
                document_id=document_id,
                storage_path=stored_file.storage_path,
                file_extension=stored_file.file_extension,
                uploaded_at=datetime.now(UTC),
            )
            if project_id is not None:
                await self.attach_document_to_project(
                    project_id=project_id,
                    document_id=document.id,
                    owner_id=owner_id,
                )
            return document, project_id
        except Exception:
            storage_service.delete_path(stored_file.storage_path)
            raise

    async def list_documents(
        self,
        *,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        documents = await self._document_repository.list_for_owner(
            owner_id=owner_id,
            limit=limit,
            offset=offset,
        )
        total = await self._document_repository.count_for_owner(owner_id=owner_id)
        return documents, total

    async def get_document(self, *, document_id: UUID, owner_id: UUID) -> Document:
        document = await self._document_repository.get_by_id(document_id)
        if document is None or document.owner_id != owner_id:
            raise DocumentNotFoundError
        return document

    async def attach_document_to_project(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
        owner_id: UUID,
    ) -> Document:
        project = await self._get_owned_project(project_id=project_id, owner_id=owner_id)
        document = await self.get_document(document_id=document_id, owner_id=owner_id)

        existing_link = await self._document_repository.get_project_document(
            project_id=project.id,
            document_id=document.id,
        )
        if existing_link is None:
            await self._document_repository.attach_to_project(
                project_id=project.id,
                document_id=document.id,
            )
            await self._document_repository.commit()

        return document

    async def detach_document_from_project(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
        owner_id: UUID,
    ) -> None:
        project = await self._get_owned_project(project_id=project_id, owner_id=owner_id)
        document = await self.get_document(document_id=document_id, owner_id=owner_id)
        existing_link = await self._document_repository.get_project_document(
            project_id=project.id,
            document_id=document.id,
        )
        if existing_link is None:
            raise ProjectDocumentLinkNotFoundError

        await self._document_repository.detach_from_project(existing_link)
        await self._document_repository.commit()

    async def list_project_documents(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Document], int]:
        project = await self._get_owned_project(project_id=project_id, owner_id=owner_id)
        documents = await self._document_repository.list_for_project(
            project_id=project.id,
            owner_id=owner_id,
            limit=limit,
            offset=offset,
        )
        total = await self._document_repository.count_for_project(
            project_id=project.id,
            owner_id=owner_id,
        )
        return documents, total

    async def _get_owned_project(self, *, project_id: UUID, owner_id: UUID) -> Project:
        project = await self._project_repository.get_by_id(project_id)
        if project is None or project.user_id != owner_id or project.is_archived:
            raise ProjectNotFoundError
        return project


class DocumentNotFoundError(Exception):
    """Raised when a document does not exist or is not owned by the user."""


class ProjectNotFoundError(Exception):
    """Raised when a project does not exist or is not owned by the user."""


class ProjectDocumentLinkNotFoundError(Exception):
    """Raised when a project-document link does not exist."""
