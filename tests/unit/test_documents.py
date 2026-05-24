from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Header, HTTPException, UploadFile, status
from fastapi.testclient import TestClient
from httpx import Response
from starlette.datastructures import Headers

from app.api.deps import (
    get_current_user,
    get_document_processing_service,
    get_document_service,
    get_local_storage_service,
    get_project_service,
)
from app.main import create_app
from app.models.document import Document, DocumentProcessingStatus, ProjectDocument
from app.models.project import Project
from app.models.user import User
from app.parsers.base import ParsedDocument
from app.parsers.registry import ParserRegistry
from app.services.document_processing_service import DocumentProcessingService
from app.services.document_service import DocumentService
from app.services.project_service import ProjectService
from app.storage.local_storage import LocalStorageService


@dataclass
class DocumentsClient:
    client: TestClient
    storage_root: Path
    document_repository: "InMemoryDocumentRepository"


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}

    async def create(self, *, user_id: UUID, name: str, description: str | None) -> Project:
        now = datetime.now(UTC)
        project = Project(user_id=user_id, name=name, description=description)
        project.id = uuid4()
        project.is_archived = False
        project.created_at = now
        project.updated_at = now
        self.projects[project.id] = project
        return project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self.projects.get(project_id)

    async def get_by_user_and_name(self, *, user_id: UUID, name: str) -> Project | None:
        return next(
            (
                project
                for project in self.projects.values()
                if project.user_id == user_id and project.name == name
            ),
            None,
        )

    async def list_for_user(self, *, user_id: UUID, limit: int, offset: int) -> list[Project]:
        projects = [
            project
            for project in self.projects.values()
            if project.user_id == user_id and not project.is_archived
        ]
        projects.sort(key=lambda project: project.updated_at, reverse=True)
        return projects[offset : offset + limit]

    async def count_for_user(self, *, user_id: UUID) -> int:
        return len(
            [
                project
                for project in self.projects.values()
                if project.user_id == user_id and not project.is_archived
            ]
        )

    async def commit(self) -> None:
        return None

    async def refresh(self, project: Project) -> None:
        project.updated_at = datetime.now(UTC)


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[UUID, Document] = {}
        self.project_documents: dict[tuple[UUID, UUID], ProjectDocument] = {}

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
        now = datetime.now(UTC)
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
        document.id = document_id or uuid4()
        document.processing_status = DocumentProcessingStatus.UPLOADED
        document.created_at = now
        document.updated_at = now
        self.documents[document.id] = document
        return document

    async def get_by_id(self, document_id: UUID) -> Document | None:
        return self.documents.get(document_id)

    async def list_for_owner(self, *, owner_id: UUID, limit: int, offset: int) -> list[Document]:
        documents = [
            document for document in self.documents.values() if document.owner_id == owner_id
        ]
        documents.sort(key=lambda document: document.updated_at, reverse=True)
        return documents[offset : offset + limit]

    async def count_for_owner(self, *, owner_id: UUID) -> int:
        return len(
            [document for document in self.documents.values() if document.owner_id == owner_id]
        )

    async def get_project_document(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
    ) -> ProjectDocument | None:
        return self.project_documents.get((project_id, document_id))

    async def attach_to_project(self, *, project_id: UUID, document_id: UUID) -> ProjectDocument:
        project_document = ProjectDocument(project_id=project_id, document_id=document_id)
        project_document.created_at = datetime.now(UTC)
        self.project_documents[(project_id, document_id)] = project_document
        return project_document

    async def detach_from_project(self, project_document: ProjectDocument) -> None:
        self.project_documents.pop(
            (project_document.project_id, project_document.document_id),
            None,
        )

    async def list_for_project(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        limit: int,
        offset: int,
    ) -> list[Document]:
        linked_document_ids = [
            document_id
            for linked_project_id, document_id in self.project_documents
            if linked_project_id == project_id
        ]
        documents = [
            self.documents[document_id]
            for document_id in linked_document_ids
            if self.documents[document_id].owner_id == owner_id
        ]
        documents.sort(key=lambda document: document.updated_at, reverse=True)
        return documents[offset : offset + limit]

    async def count_for_project(self, *, project_id: UUID, owner_id: UUID) -> int:
        return len(
            await self.list_for_project(
                project_id=project_id,
                owner_id=owner_id,
                limit=10_000,
                offset=0,
            )
        )

    async def commit(self) -> None:
        return None

    async def refresh(self, document: Document) -> None:
        document.updated_at = datetime.now(UTC)


@pytest.fixture
def documents_client(tmp_path: Path) -> Iterator[DocumentsClient]:
    app = create_app()
    project_repository = InMemoryProjectRepository()
    document_repository = InMemoryDocumentRepository()
    storage_service = _build_storage_service(tmp_path)
    project_service = ProjectService(project_repository=project_repository)  # type: ignore[arg-type]
    document_service = DocumentService(  # type: ignore[arg-type]
        document_repository=document_repository,
        project_repository=project_repository,
    )
    processing_service = DocumentProcessingService(  # type: ignore[arg-type]
        document_repository=document_repository,
        parser_registry=ParserRegistry(),
        storage_service=storage_service,
        max_extracted_text_chars=10_000,
    )
    users = {
        "user-one": _build_user(email="one@example.com"),
        "user-two": _build_user(email="two@example.com"),
    }

    async def override_current_user(
        authorization: Annotated[str | None, Header()] = None,
    ) -> User:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        user = users.get(authorization.removeprefix("Bearer "))
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return user

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_project_service] = lambda: project_service
    app.dependency_overrides[get_document_service] = lambda: document_service
    app.dependency_overrides[get_document_processing_service] = lambda: processing_service
    app.dependency_overrides[get_local_storage_service] = lambda: storage_service

    with TestClient(app) as client:
        yield DocumentsClient(
            client=client,
            storage_root=tmp_path,
            document_repository=document_repository,
        )

    app.dependency_overrides.clear()


def test_create_list_get_document(documents_client: DocumentsClient) -> None:
    create_response = _create_document(documents_client.client, title="Spec")
    document_id = create_response.json()["id"]

    list_response = documents_client.client.get("/api/v1/documents", headers=_auth_headers())
    get_response = documents_client.client.get(
        f"/api/v1/documents/{document_id}",
        headers=_auth_headers(),
    )

    assert create_response.status_code == 201
    assert create_response.json()["title"] == "Spec"
    assert create_response.json()["processing_status"] == "uploaded"
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert get_response.status_code == 200
    assert get_response.json()["id"] == document_id


def test_documents_require_auth(documents_client: DocumentsClient) -> None:
    response = documents_client.client.get("/api/v1/documents")

    assert response.status_code == 401


def test_document_ownership_isolation(documents_client: DocumentsClient) -> None:
    foreign_document = _create_document(documents_client.client, title="Foreign", token="user-two")

    response = documents_client.client.get(
        f"/api/v1/documents/{foreign_document.json()['id']}",
        headers=_auth_headers(),
    )

    assert response.status_code == 404


def test_attach_duplicate_attach_detach_and_list_project_documents(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Research")
    document = _create_document(documents_client.client, title="Notes")
    attach_url = f"/api/v1/projects/{project.json()['id']}/documents/{document.json()['id']}"

    attach_response = documents_client.client.post(attach_url, headers=_auth_headers())
    duplicate_attach_response = documents_client.client.post(attach_url, headers=_auth_headers())
    list_response = documents_client.client.get(
        f"/api/v1/projects/{project.json()['id']}/documents",
        headers=_auth_headers(),
    )
    detach_response = documents_client.client.delete(attach_url, headers=_auth_headers())
    list_after_detach_response = documents_client.client.get(
        f"/api/v1/projects/{project.json()['id']}/documents",
        headers=_auth_headers(),
    )

    assert attach_response.status_code == 200
    assert duplicate_attach_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert detach_response.status_code == 204
    assert list_after_detach_response.json()["total"] == 0


def test_foreign_project_or_document_linking_is_blocked(
    documents_client: DocumentsClient,
) -> None:
    own_project = _create_project(documents_client.client, name="Own")
    own_document = _create_document(documents_client.client, title="Own doc")
    foreign_project = _create_project(documents_client.client, name="Foreign", token="user-two")
    foreign_document = _create_document(
        documents_client.client,
        title="Foreign doc",
        token="user-two",
    )

    foreign_project_response = documents_client.client.post(
        f"/api/v1/projects/{foreign_project.json()['id']}/documents/{own_document.json()['id']}",
        headers=_auth_headers(),
    )
    foreign_document_response = documents_client.client.post(
        f"/api/v1/projects/{own_project.json()['id']}/documents/{foreign_document.json()['id']}",
        headers=_auth_headers(),
    )

    assert foreign_project_response.status_code == 404
    assert foreign_document_response.status_code == 404


def test_upload_document_ok_generates_storage_path_and_hash(
    documents_client: DocumentsClient,
) -> None:
    response = _upload_document(
        documents_client.client,
        filename="notes.txt",
        content=b"hello world",
        content_type="text/plain",
    )

    body = response.json()
    storage_path = body["document"]["storage_path"]

    assert response.status_code == 201
    assert body["document"]["original_filename"] == "notes.txt"
    assert body["document"]["file_extension"] == "txt"
    assert body["document"]["content_hash"] == (
        "b94d27b9934d3e08a52e52d7da7dabfa"
        "c484efe37a5380ee9088f7ace2efcde9"
    )
    assert body["document"]["processing_status"] == "uploaded"
    assert storage_path.endswith("/original.txt")
    assert (documents_client.storage_root / storage_path).exists()


def test_upload_rejects_invalid_mime_oversized_empty_and_requires_auth(
    documents_client: DocumentsClient,
) -> None:
    invalid_mime_response = _upload_document(
        documents_client.client,
        filename="notes.txt",
        content=b"hello",
        content_type="application/octet-stream",
    )
    oversized_response = _upload_document(
        documents_client.client,
        filename="big.txt",
        content=b"a" * 2049,
        content_type="text/plain",
    )
    empty_response = _upload_document(
        documents_client.client,
        filename="empty.txt",
        content=b"",
        content_type="text/plain",
    )
    unauthenticated_response = documents_client.client.post(
        "/api/v1/documents/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )

    assert invalid_mime_response.status_code == 400
    assert oversized_response.status_code == 413
    assert empty_response.status_code == 400
    assert unauthenticated_response.status_code == 401


def test_upload_rejects_invalid_extension_even_with_valid_mime(
    documents_client: DocumentsClient,
) -> None:
    response = _upload_document(
        documents_client.client,
        filename="malware.exe",
        content=b"plain text",
        content_type="text/plain",
    )

    assert response.status_code == 400


def test_upload_can_attach_to_own_project_and_rejects_foreign_project(
    documents_client: DocumentsClient,
) -> None:
    own_project = _create_project(documents_client.client, name="Own")
    foreign_project = _create_project(documents_client.client, name="Foreign", token="user-two")

    own_response = _upload_document(
        documents_client.client,
        filename="own.pdf",
        content=b"%PDF-1.4",
        content_type="application/pdf",
        project_id=own_project.json()["id"],
    )
    foreign_response = _upload_document(
        documents_client.client,
        filename="foreign.pdf",
        content=b"%PDF-1.4",
        content_type="application/pdf",
        project_id=foreign_project.json()["id"],
    )
    list_response = documents_client.client.get(
        f"/api/v1/projects/{own_project.json()['id']}/documents",
        headers=_auth_headers(),
    )

    assert own_response.status_code == 201
    assert own_response.json()["linked_project_id"] == own_project.json()["id"]
    assert foreign_response.status_code == 404
    assert list_response.json()["total"] == 1


def test_upload_duplicate_filenames_use_distinct_uuid_paths(
    documents_client: DocumentsClient,
) -> None:
    first_response = _upload_document(
        documents_client.client,
        filename="duplicate.md",
        content=b"# one",
        content_type="text/markdown",
    )
    second_response = _upload_document(
        documents_client.client,
        filename="duplicate.md",
        content=b"# two",
        content_type="text/markdown",
    )

    first_path = first_response.json()["document"]["storage_path"]
    second_path = second_response.json()["document"]["storage_path"]

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_path != second_path
    assert (documents_client.storage_root / first_path).exists()
    assert (documents_client.storage_root / second_path).exists()


def test_upload_sanitizes_path_traversal_filename(documents_client: DocumentsClient) -> None:
    response = _upload_document(
        documents_client.client,
        filename="../../evil.txt",
        content=b"safe",
        content_type="text/plain",
    )

    body = response.json()
    storage_path = body["document"]["storage_path"]

    assert response.status_code == 201
    assert body["document"]["original_filename"] == "evil.txt"
    assert ".." not in storage_path
    assert (documents_client.storage_root / storage_path).resolve().is_relative_to(
        documents_client.storage_root.resolve()
    )


def test_process_txt_document_ok_and_persists_extracted_text(
    documents_client: DocumentsClient,
) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="notes.txt",
        content=b"hello\r\nworld",
        content_type="text/plain",
    )
    document_id = upload_response.json()["document"]["id"]

    process_response = documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(),
    )
    content_response = documents_client.client.get(
        f"/api/v1/documents/{document_id}/content",
        headers=_auth_headers(),
    )

    assert process_response.status_code == 200
    assert process_response.json()["processing_status"] == "ready"
    assert process_response.json()["extracted_text_length"] == 11
    assert content_response.status_code == 200
    assert content_response.json()["extracted_text"] == "hello\nworld"
    assert content_response.json()["extracted_text_length"] == 11


def test_process_markdown_document_ok(documents_client: DocumentsClient) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="notes.md",
        content=b"# Title\r\nBody",
        content_type="text/markdown",
    )
    document_id = upload_response.json()["document"]["id"]

    response = documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["processing_status"] == "ready"
    assert response.json()["extracted_text_length"] == len("# Title\nBody")


def test_process_unsupported_type_sets_failed_status(documents_client: DocumentsClient) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="paper.pdf",
        content=b"%PDF-1.4",
        content_type="application/pdf",
    )
    document_id = upload_response.json()["document"]["id"]

    response = documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["processing_status"] == "failed"
    assert response.json()["processing_error"] is not None


def test_process_missing_file_sets_failed_status(documents_client: DocumentsClient) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="missing.txt",
        content=b"temporary",
        content_type="text/plain",
    )
    document = upload_response.json()["document"]
    (documents_client.storage_root / document["storage_path"]).unlink()

    response = documents_client.client.post(
        f"/api/v1/documents/{document['id']}/process",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["processing_status"] == "failed"
    assert response.json()["processing_error"] is not None


def test_process_can_reprocess_ready_document(documents_client: DocumentsClient) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="reprocess.txt",
        content=b"first",
        content_type="text/plain",
    )
    document = upload_response.json()["document"]
    process_url = f"/api/v1/documents/{document['id']}/process"

    first_response = documents_client.client.post(process_url, headers=_auth_headers())
    second_response = documents_client.client.post(process_url, headers=_auth_headers())

    assert first_response.status_code == 200
    assert first_response.json()["processing_status"] == "ready"
    assert second_response.status_code == 200
    assert second_response.json()["processing_status"] == "ready"


def test_process_blocks_document_already_processing(documents_client: DocumentsClient) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="processing.txt",
        content=b"processing",
        content_type="text/plain",
    )
    document_id = UUID(upload_response.json()["document"]["id"])
    document = _get_document_from_test_app(documents_client, document_id)
    document.processing_status = DocumentProcessingStatus.PROCESSING

    response = documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(),
    )

    assert response.status_code == 409


def test_process_ownership_isolation_and_auth_required(
    documents_client: DocumentsClient,
) -> None:
    foreign_upload = _upload_document(
        documents_client.client,
        filename="foreign.txt",
        content=b"secret",
        content_type="text/plain",
        token="user-two",
    )
    foreign_document_id = foreign_upload.json()["document"]["id"]

    foreign_response = documents_client.client.post(
        f"/api/v1/documents/{foreign_document_id}/process",
        headers=_auth_headers(),
    )
    unauthenticated_response = documents_client.client.post(
        f"/api/v1/documents/{foreign_document_id}/process",
    )

    assert foreign_response.status_code == 404
    assert unauthenticated_response.status_code == 401


@pytest.mark.asyncio
async def test_parser_exception_sets_failed_status(tmp_path: Path) -> None:
    project_repository = InMemoryProjectRepository()
    document_repository = InMemoryDocumentRepository()
    storage_service = _build_storage_service(tmp_path)
    document_service = DocumentService(  # type: ignore[arg-type]
        document_repository=document_repository,
        project_repository=project_repository,
    )
    processing_service = DocumentProcessingService(  # type: ignore[arg-type]
        document_repository=document_repository,
        parser_registry=FailingParserRegistry(),
        storage_service=storage_service,
        max_extracted_text_chars=10_000,
    )
    owner_id = uuid4()
    document, _ = await document_service.upload_document(
        owner_id=owner_id,
        upload_file=_build_upload_file(
            filename="broken.txt",
            content=b"broken",
            content_type="text/plain",
        ),
        storage_service=storage_service,
        project_id=None,
    )

    processed_document = await processing_service.process_document(
        document_id=document.id,
        owner_id=owner_id,
    )

    assert processed_document.processing_status == DocumentProcessingStatus.FAILED
    assert processed_document.processing_error == "parser exploded"


@pytest.mark.asyncio
async def test_upload_cleans_file_when_metadata_write_fails(tmp_path: Path) -> None:
    project_repository = InMemoryProjectRepository()
    document_repository = FailingDocumentRepository()
    document_service = DocumentService(  # type: ignore[arg-type]
        document_repository=document_repository,
        project_repository=project_repository,
    )
    upload_file = _build_upload_file(
        filename="cleanup.txt",
        content=b"cleanup",
        content_type="text/plain",
    )

    with pytest.raises(RuntimeError):
        await document_service.upload_document(
            owner_id=uuid4(),
            upload_file=upload_file,
            storage_service=_build_storage_service(tmp_path),
            project_id=None,
        )

    assert not any(tmp_path.rglob("*.*"))


class FailingDocumentRepository(InMemoryDocumentRepository):
    async def create(self, **kwargs: object) -> Document:
        raise RuntimeError("simulated db write failure")


class ExplodingParser:
    def parse(self, path: Path, *, max_chars: int) -> ParsedDocument:
        raise RuntimeError("parser exploded")


class FailingParserRegistry:
    def get_parser(self, *, mime_type: str, file_extension: str | None) -> ExplodingParser:
        return ExplodingParser()


def _get_document_from_test_app(documents_client: DocumentsClient, document_id: UUID) -> Document:
    return documents_client.document_repository.documents[document_id]


def _build_user(*, email: str) -> User:
    user = User(email=email, hashed_password="not-used")
    user.id = uuid4()
    user.is_active = True
    return user


def _auth_headers(token: str = "user-one") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_project(client: TestClient, *, name: str, token: str = "user-one") -> Response:
    return client.post(
        "/api/v1/projects",
        json={"name": name, "description": f"{name} description"},
        headers=_auth_headers(token),
    )


def _create_document(client: TestClient, *, title: str, token: str = "user-one") -> Response:
    return client.post(
        "/api/v1/documents",
        json={
            "title": title,
            "original_filename": f"{title}.txt",
            "mime_type": "text/plain",
            "file_size_bytes": 128,
            "storage_provider": "local",
            "content_hash": None,
        },
        headers=_auth_headers(token),
    )


def _upload_document(
    client: TestClient,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    token: str = "user-one",
    project_id: str | None = None,
) -> Response:
    data = {"project_id": project_id} if project_id is not None else None
    return client.post(
        "/api/v1/documents/upload",
        data=data,
        files={"file": (filename, content, content_type)},
        headers=_auth_headers(token),
    )


def _build_storage_service(storage_root: Path) -> LocalStorageService:
    return LocalStorageService(
        storage_root=storage_root,
        max_upload_size_bytes=2048,
        allowed_extensions={"pdf", "txt", "md", "docx"},
        allowed_mime_types={
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/markdown",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )


def _build_upload_file(*, filename: str, content: bytes, content_type: str) -> UploadFile:
    file = SpooledTemporaryFile()
    file.write(content)
    file.seek(0)
    return UploadFile(file=file, filename=filename, headers=Headers({"content-type": content_type}))
