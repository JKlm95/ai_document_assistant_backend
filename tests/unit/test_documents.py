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
    get_document_embedding_service,
    get_document_processing_service,
    get_document_service,
    get_local_storage_service,
    get_project_retriever,
    get_project_service,
    get_rag_answer_service,
)
from app.chunking.fixed_size_chunker import FixedSizeChunkingStrategy
from app.chunking.models import ChunkResult
from app.embeddings.base import EmbeddingProviderError
from app.embeddings.models import EmbeddingResult
from app.embeddings.providers.mock import MockEmbeddingProvider
from app.embeddings.registry import EmbeddingProviderRegistry
from app.llm.base import LLMProviderError
from app.llm.models import LLMResult
from app.llm.providers.mock_provider import MockLLMProvider
from app.llm.registry import LLMProviderRegistry
from app.main import create_app
from app.models.document import (
    Document,
    DocumentClassification,
    DocumentProcessingMode,
    DocumentProcessingStatus,
    ProjectDocument,
)
from app.models.document_chunk import ChunkEmbeddingStatus, DocumentChunk
from app.models.project import Project
from app.models.user import User
from app.parsers.base import ParsedDocument
from app.parsers.registry import ParserRegistry
from app.rag.context_builder import ContextBuilder
from app.rag.models import RetrievalResult, SourceReference
from app.rag.prompt_builder import PromptBuilder
from app.rag.retriever import ProjectRetriever
from app.services.document_embedding_service import DocumentEmbeddingService
from app.services.document_processing_service import DocumentProcessingService
from app.services.document_service import DocumentService
from app.services.project_service import ProjectService
from app.services.rag_answer_service import RagAnswerService
from app.storage.local_storage import LocalStorageService


@dataclass
class DocumentsClient:
    client: TestClient
    storage_root: Path
    document_repository: "InMemoryDocumentRepository"
    project_repository: "InMemoryProjectRepository"


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
        self.chunks: dict[UUID, list[DocumentChunk]] = {}
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
        classification: DocumentClassification = DocumentClassification.INTERNAL,
        processing_mode: DocumentProcessingMode = DocumentProcessingMode.PREFER_LOCAL,
        language: str | None = None,
        country: str | None = None,
        document_type: str | None = None,
        tags: list[str] | None = None,
        source_url: str | None = None,
        version: str | None = None,
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
        document.chunk_count = 0
        document.chunked_at = None
        document.classification = classification
        document.processing_mode = processing_mode
        document.language = language
        document.country = country
        document.document_type = document_type
        document.tags = tags
        document.source_url = source_url
        document.version = version
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

    async def delete_chunks_for_document(self, *, document_id: UUID) -> None:
        self.chunks[document_id] = []

    async def create_chunks(
        self,
        *,
        document_id: UUID,
        chunks: list[ChunkResult],
    ) -> list[DocumentChunk]:
        now = datetime.now(UTC)
        document_chunks = []
        for chunk in chunks:
            document_chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                char_count=chunk.char_count,
                token_count_estimate=chunk.token_count_estimate,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
            )
            document_chunk.id = uuid4()
            document_chunk.embedding_status = ChunkEmbeddingStatus.PENDING
            document_chunk.embedding_provider = None
            document_chunk.embedding_model = None
            document_chunk.embedded_at = None
            document_chunk.embedding_error = None
            document_chunk.embedding_dimensions = None
            document_chunk.embedding_vector = None
            document_chunk.created_at = now
            document_chunks.append(document_chunk)
        self.chunks[document_id] = document_chunks
        return document_chunks

    async def list_chunks_for_document(self, *, document_id: UUID) -> list[DocumentChunk]:
        return sorted(
            self.chunks.get(document_id, []),
            key=lambda chunk: chunk.chunk_index,
        )

    async def reset_embeddings_for_document(self, *, document_id: UUID) -> None:
        for chunk in self.chunks.get(document_id, []):
            chunk.embedding_provider = None
            chunk.embedding_model = None
            chunk.embedded_at = None
            chunk.embedding_error = None
            chunk.embedding_status = ChunkEmbeddingStatus.PENDING
            chunk.embedding_dimensions = None
            chunk.embedding_vector = None

    async def search_similar_chunks(
        self,
        *,
        owner_id: UUID,
        query_vector: list[float],
        limit: int,
    ) -> list[tuple[DocumentChunk, float]]:
        candidates: list[tuple[DocumentChunk, float]] = []
        for document_id, chunks in self.chunks.items():
            document = self.documents[document_id]
            if document.owner_id != owner_id:
                continue
            for chunk in chunks:
                if (
                    chunk.embedding_status != ChunkEmbeddingStatus.EMBEDDED
                    or chunk.embedding_vector is None
                ):
                    continue
                candidates.append((chunk, _cosine_similarity(query_vector, chunk.embedding_vector)))
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:limit]

    async def search_similar_chunks_for_project(
        self,
        *,
        owner_id: UUID,
        project_id: UUID,
        query_vector: list[float],
        limit: int,
    ) -> list[tuple[DocumentChunk, Document, float]]:
        candidates: list[tuple[DocumentChunk, Document, float]] = []
        linked_document_ids = {
            document_id
            for linked_project_id, document_id in self.project_documents
            if linked_project_id == project_id
        }
        for document_id in linked_document_ids:
            document = self.documents[document_id]
            if document.owner_id != owner_id:
                continue
            for chunk in self.chunks.get(document_id, []):
                if (
                    chunk.embedding_status != ChunkEmbeddingStatus.EMBEDDED
                    or chunk.embedding_vector is None
                ):
                    continue
                candidates.append(
                    (document, chunk, _cosine_similarity(query_vector, chunk.embedding_vector))
                )
        candidates.sort(key=lambda item: item[2], reverse=True)
        return [(chunk, document, score) for document, chunk, score in candidates[:limit]]

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
        chunking_strategy=FixedSizeChunkingStrategy(
            chunk_size_chars=10,
            chunk_overlap_chars=2,
        ),
        storage_service=storage_service,
        max_extracted_text_chars=10_000,
    )
    embedding_service = DocumentEmbeddingService(  # type: ignore[arg-type]
        document_repository=document_repository,
        embedding_provider=MockEmbeddingProvider(
            model_name="mock-embedding",
            dimensions=8,
        ),
        embedding_dimensions=8,
    )
    project_retriever = ProjectRetriever(  # type: ignore[arg-type]
        project_repository=project_repository,
        document_repository=document_repository,
        embedding_provider=MockEmbeddingProvider(
            model_name="mock-embedding",
            dimensions=8,
        ),
        embedding_dimensions=8,
        context_builder=ContextBuilder(max_chars=500),
        default_limit=5,
        max_limit=3,
    )
    rag_answer_service = RagAnswerService(
        project_retriever=project_retriever,
        llm_provider=MockLLMProvider(model_name="mock-rag-answer"),
        prompt_builder=PromptBuilder(),
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
    app.dependency_overrides[get_document_embedding_service] = lambda: embedding_service
    app.dependency_overrides[get_project_retriever] = lambda: project_retriever
    app.dependency_overrides[get_rag_answer_service] = lambda: rag_answer_service
    app.dependency_overrides[get_local_storage_service] = lambda: storage_service

    with TestClient(app) as client:
        yield DocumentsClient(
            client=client,
            storage_root=tmp_path,
            document_repository=document_repository,
            project_repository=project_repository,
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
    assert process_response.json()["chunk_count"] == 2
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
    assert response.json()["chunk_count"] == 2


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
    assert response.json()["chunk_count"] == 0


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
    assert response.json()["chunk_count"] == 0


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


def test_chunk_endpoint_returns_ordered_chunks_and_count(
    documents_client: DocumentsClient,
) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="chunked.txt",
        content=b"abcdefghij klmnopqrst uvwxyz",
        content_type="text/plain",
    )
    document_id = upload_response.json()["document"]["id"]

    process_response = documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(),
    )
    chunks_response = documents_client.client.get(
        f"/api/v1/documents/{document_id}/chunks",
        headers=_auth_headers(),
    )

    chunks = chunks_response.json()["chunks"]
    assert process_response.status_code == 200
    assert chunks_response.status_code == 200
    assert chunks_response.json()["chunk_count"] == process_response.json()["chunk_count"]
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0]["text"] == "abcdefghij"
    assert chunks[1]["text"].startswith("ij klmnop")


def test_chunking_is_deterministic() -> None:
    chunker = FixedSizeChunkingStrategy(chunk_size_chars=8, chunk_overlap_chars=2)
    text = "alpha beta gamma"

    first_chunks = chunker.chunk(text)
    second_chunks = chunker.chunk(text)

    assert first_chunks == second_chunks


def test_chunking_handles_tiny_and_empty_text() -> None:
    chunker = FixedSizeChunkingStrategy(chunk_size_chars=10, chunk_overlap_chars=2)

    tiny_chunks = chunker.chunk("tiny")
    empty_chunks = chunker.chunk(" \n\t ")

    assert len(tiny_chunks) == 1
    assert tiny_chunks[0].text == "tiny"
    assert empty_chunks == []


def test_chunker_rejects_overlap_greater_than_or_equal_to_chunk_size() -> None:
    with pytest.raises(ValueError, match="smaller than chunk_size_chars"):
        FixedSizeChunkingStrategy(chunk_size_chars=10, chunk_overlap_chars=10)


def test_reprocess_replaces_chunks(documents_client: DocumentsClient) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="replace.txt",
        content=b"first second third fourth",
        content_type="text/plain",
    )
    document = upload_response.json()["document"]
    process_url = f"/api/v1/documents/{document['id']}/process"
    chunks_url = f"/api/v1/documents/{document['id']}/chunks"

    first_response = documents_client.client.post(process_url, headers=_auth_headers())
    storage_path = documents_client.storage_root / document["storage_path"]
    storage_path.write_text("short", encoding="utf-8")
    second_response = documents_client.client.post(process_url, headers=_auth_headers())
    chunks_response = documents_client.client.get(chunks_url, headers=_auth_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["chunk_count"] == 1
    assert chunks_response.json()["chunks"][0]["text"] == "short"


def test_whitespace_only_text_produces_zero_chunks(documents_client: DocumentsClient) -> None:
    upload_response = _upload_document(
        documents_client.client,
        filename="empty-content.txt",
        content=b" \n\t ",
        content_type="text/plain",
    )
    document_id = upload_response.json()["document"]["id"]

    process_response = documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(),
    )
    chunks_response = documents_client.client.get(
        f"/api/v1/documents/{document_id}/chunks",
        headers=_auth_headers(),
    )

    assert process_response.status_code == 200
    assert process_response.json()["processing_status"] == "ready"
    assert process_response.json()["chunk_count"] == 0
    assert chunks_response.json()["chunks"] == []


def test_chunks_endpoint_ownership_isolation_and_auth_required(
    documents_client: DocumentsClient,
) -> None:
    foreign_upload = _upload_document(
        documents_client.client,
        filename="foreign-chunks.txt",
        content=b"secret chunks",
        content_type="text/plain",
        token="user-two",
    )
    foreign_document_id = foreign_upload.json()["document"]["id"]

    foreign_response = documents_client.client.get(
        f"/api/v1/documents/{foreign_document_id}/chunks",
        headers=_auth_headers(),
    )
    unauthenticated_response = documents_client.client.get(
        f"/api/v1/documents/{foreign_document_id}/chunks",
    )

    assert foreign_response.status_code == 404
    assert unauthenticated_response.status_code == 401


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
async def test_mock_embeddings_are_deterministic() -> None:
    provider = MockEmbeddingProvider(model_name="mock", dimensions=8)

    first = await provider.embed_texts(["alpha"])
    second = await provider.embed_texts(["alpha"])

    assert first == second
    assert first[0].dimensions == 8


def test_embedding_provider_registry_returns_mock_and_rejects_unknown() -> None:
    registry = EmbeddingProviderRegistry(
        provider_name="mock",
        model_name="mock",
        dimensions=8,
        openai_api_key=None,
    )

    provider = registry.get_provider()

    assert provider.provider_name == "mock"
    with pytest.raises(EmbeddingProviderError):
        EmbeddingProviderRegistry(
            provider_name="unsupported",
            model_name="mock",
            dimensions=8,
            openai_api_key=None,
        ).get_provider()


def test_embed_document_persists_vectors_and_statuses(documents_client: DocumentsClient) -> None:
    document_id = _upload_process_and_embed(documents_client, content=b"alpha beta gamma")

    status_response = documents_client.client.get(
        f"/api/v1/documents/{document_id}/embedding-status",
        headers=_auth_headers(),
    )
    chunks_response = documents_client.client.get(
        f"/api/v1/documents/{document_id}/chunks",
        headers=_auth_headers(),
    )

    assert status_response.status_code == 200
    assert status_response.json()["embedded_chunks"] == status_response.json()["total_chunks"]
    assert status_response.json()["pending_chunks"] == 0
    assert status_response.json()["failed_chunks"] == 0
    assert status_response.json()["document"]["processing_status"] == "ready"
    assert chunks_response.json()["chunks"][0]["embedding_status"] == "embedded"
    assert chunks_response.json()["chunks"][0]["embedding_dimensions"] == 8


def test_reindex_replaces_embeddings(documents_client: DocumentsClient) -> None:
    document_id = _upload_process_and_embed(documents_client, content=b"alpha beta gamma")
    document_chunks = documents_client.document_repository.chunks[UUID(document_id)]
    first_vector = document_chunks[0].embedding_vector

    embed_response = documents_client.client.post(
        f"/api/v1/documents/{document_id}/embed",
        headers=_auth_headers(),
    )
    second_vector = document_chunks[0].embedding_vector

    assert embed_response.status_code == 200
    assert first_vector == second_vector
    assert embed_response.json()["embedded_chunks"] == embed_response.json()["total_chunks"]


def test_similar_chunks_orders_by_similarity(documents_client: DocumentsClient) -> None:
    first_document_id = _upload_process_and_embed(
        documents_client,
        filename="alpha.txt",
        content=b"alpha alpha alpha",
    )
    _upload_process_and_embed(
        documents_client,
        filename="zulu.txt",
        content=b"zulu zulu zulu",
    )

    response = documents_client.client.get(
        f"/api/v1/documents/{first_document_id}/similar-chunks?q=alpha&limit=2",
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert items[0]["similarity_score"] >= items[1]["similarity_score"]
    assert "alpha" in items[0]["text"]


def test_embedding_ownership_and_vector_search_isolation(
    documents_client: DocumentsClient,
) -> None:
    owned_document_id = _upload_process_and_embed(
        documents_client,
        filename="owned.txt",
        content=b"owned alpha",
    )
    foreign_upload = _upload_document(
        documents_client.client,
        filename="foreign-embed.txt",
        content=b"foreign alpha",
        content_type="text/plain",
        token="user-two",
    )
    foreign_document_id = foreign_upload.json()["document"]["id"]
    documents_client.client.post(
        f"/api/v1/documents/{foreign_document_id}/process",
        headers=_auth_headers("user-two"),
    )
    documents_client.client.post(
        f"/api/v1/documents/{foreign_document_id}/embed",
        headers=_auth_headers("user-two"),
    )

    foreign_status_response = documents_client.client.get(
        f"/api/v1/documents/{foreign_document_id}/embedding-status",
        headers=_auth_headers(),
    )
    search_response = documents_client.client.get(
        f"/api/v1/documents/{owned_document_id}/similar-chunks?q=alpha&limit=10",
        headers=_auth_headers(),
    )

    assert foreign_status_response.status_code == 404
    assert search_response.status_code == 200
    assert all("foreign" not in item["text"] for item in search_response.json()["items"])


@pytest.mark.asyncio
async def test_invalid_embedding_dimensions_marks_chunk_failed(tmp_path: Path) -> None:
    document_repository, document = await _build_processed_document_for_embedding_test(tmp_path)
    service = DocumentEmbeddingService(  # type: ignore[arg-type]
        document_repository=document_repository,
        embedding_provider=WrongDimensionsProvider(),
        embedding_dimensions=8,
    )

    summary = await service.embed_document(document_id=document.id, owner_id=document.owner_id)

    assert summary.failed_chunks == summary.total_chunks
    assert summary.document.processing_status == DocumentProcessingStatus.FAILED


@pytest.mark.asyncio
async def test_partial_chunk_failure_keeps_successful_embeddings(tmp_path: Path) -> None:
    document_repository, document = await _build_processed_document_for_embedding_test(
        tmp_path,
        content=b"good chunk bad chunk",
    )
    service = DocumentEmbeddingService(  # type: ignore[arg-type]
        document_repository=document_repository,
        embedding_provider=PartiallyFailingProvider(),
        embedding_dimensions=8,
    )

    summary = await service.embed_document(document_id=document.id, owner_id=document.owner_id)

    assert summary.embedded_chunks >= 1
    assert summary.failed_chunks >= 1
    assert summary.document.processing_status == DocumentProcessingStatus.READY


def test_similar_chunks_requires_auth(documents_client: DocumentsClient) -> None:
    document_id = _upload_process_and_embed(documents_client, content=b"auth alpha")

    response = documents_client.client.get(
        f"/api/v1/documents/{document_id}/similar-chunks?q=alpha",
    )

    assert response.status_code == 401


def test_project_search_returns_only_chunks_from_project(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Retrieval")
    other_project = _create_project(documents_client.client, name="Other retrieval")
    project_id = project.json()["id"]
    other_project_id = other_project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="target.txt",
        content=b"alpha project target",
    )
    _upload_process_embed_and_attach(
        documents_client,
        project_id=other_project_id,
        filename="other.txt",
        content=b"alpha other project",
    )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "alpha", "limit": 5},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["results"]
    assert all("other project" not in item["text"] for item in response.json()["results"])


def test_project_search_does_not_leak_foreign_user_chunks(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Own retrieval")
    foreign_project = _create_project(
        documents_client.client,
        name="Foreign retrieval",
        token="user-two",
    )
    project_id = project.json()["id"]
    foreign_project_id = foreign_project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="own-search.txt",
        content=b"shared alpha own",
    )
    _upload_process_embed_and_attach(
        documents_client,
        project_id=foreign_project_id,
        filename="foreign-search.txt",
        content=b"shared alpha foreign",
        token="user-two",
    )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "shared alpha", "limit": 10},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert all("foreign" not in item["text"] for item in response.json()["results"])


def test_project_search_empty_project_returns_empty_results(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Empty retrieval")

    response = documents_client.client.post(
        f"/api/v1/projects/{project.json()['id']}/search",
        json={"query": "anything"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert response.json()["citations"] == []
    assert response.json()["context"] == ""


def test_project_search_ignores_unembedded_chunks(documents_client: DocumentsClient) -> None:
    project = _create_project(documents_client.client, name="Pending chunks")
    project_id = project.json()["id"]
    upload = _upload_document(
        documents_client.client,
        filename="pending.txt",
        content=b"pending alpha",
        content_type="text/plain",
        project_id=project_id,
    )
    document_id = upload.json()["document"]["id"]
    documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(),
    )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "pending alpha"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_project_search_clamps_limit_to_configured_max(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Limit retrieval")
    project_id = project.json()["id"]
    for index in range(5):
        _upload_process_embed_and_attach(
            documents_client,
            project_id=project_id,
            filename=f"limit-{index}.txt",
            content=f"alpha document {index}".encode(),
        )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "alpha", "limit": 99},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert len(response.json()["results"]) == 3


def test_project_search_context_and_citations(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Citations")
    project_id = project.json()["id"]
    document_id = _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="citations.txt",
        content=b"citation alpha source",
    )
    documents_client.document_repository.documents[UUID(document_id)].source_url = (
        "https://example.com/source"
    )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "citation alpha", "limit": 1},
        headers=_auth_headers(),
    )

    body = response.json()
    assert response.status_code == 200
    assert "[1]" in body["context"]
    assert body["citations"][0]["citation_id"] == "[1]"
    assert body["citations"][0]["document_id"] == document_id
    assert body["citations"][0]["chunk_id"] == body["results"][0]["chunk_id"]
    assert body["citations"][0]["page_number"] is None
    assert body["citations"][0]["source_url"] == "https://example.com/source"


def test_context_builder_respects_max_chars() -> None:
    project_id = uuid4()
    source = _build_source_reference(project_id=project_id, index=1)
    result = _build_retrieval_result(project_id=project_id, source=source, text="x" * 100)

    context = ContextBuilder(max_chars=30).build_context([result])

    assert len(context) <= 30
    assert context.startswith("[1]")


def test_project_search_requires_auth_and_foreign_project_returns_404(
    documents_client: DocumentsClient,
) -> None:
    foreign_project = _create_project(
        documents_client.client,
        name="Foreign search",
        token="user-two",
    )

    unauthenticated_response = documents_client.client.post(
        f"/api/v1/projects/{foreign_project.json()['id']}/search",
        json={"query": "alpha"},
    )
    foreign_response = documents_client.client.post(
        f"/api/v1/projects/{foreign_project.json()['id']}/search",
        json={"query": "alpha"},
        headers=_auth_headers(),
    )
    missing_response = documents_client.client.post(
        f"/api/v1/projects/{uuid4()}/search",
        json={"query": "alpha"},
        headers=_auth_headers(),
    )

    assert unauthenticated_response.status_code == 401
    assert foreign_response.status_code == 404
    assert missing_response.status_code == 404


def test_project_search_provider_dimension_mismatch_is_503(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Bad dimensions")
    project_id = project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="bad-dimensions.txt",
        content=b"alpha bad dimensions",
    )
    bad_retriever = ProjectRetriever(  # type: ignore[arg-type]
        project_repository=documents_client.project_repository,
        document_repository=documents_client.document_repository,
        embedding_provider=WrongDimensionsProvider(),
        embedding_dimensions=8,
        context_builder=ContextBuilder(max_chars=500),
        default_limit=5,
        max_limit=5,
    )
    documents_client.client.app.dependency_overrides[get_project_retriever] = lambda: bad_retriever

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "alpha"},
        headers=_auth_headers(),
    )

    assert response.status_code == 503


def test_project_search_provider_unavailable_is_503(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Unavailable provider")
    project_id = project.json()["id"]
    bad_retriever = ProjectRetriever(  # type: ignore[arg-type]
        project_repository=documents_client.project_repository,
        document_repository=documents_client.document_repository,
        embedding_provider=UnavailableProvider(),
        embedding_dimensions=8,
        context_builder=ContextBuilder(max_chars=500),
        default_limit=5,
        max_limit=5,
    )
    documents_client.client.app.dependency_overrides[get_project_retriever] = lambda: bad_retriever

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "alpha"},
        headers=_auth_headers(),
    )

    assert response.status_code == 503


def test_project_search_is_deterministic_with_mock_provider(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Deterministic retrieval")
    project_id = project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="deterministic.txt",
        content=b"alpha deterministic retrieval",
    )

    first_response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "alpha deterministic"},
        headers=_auth_headers(),
    )
    second_response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/search",
        json={"query": "alpha deterministic"},
        headers=_auth_headers(),
    )

    assert first_response.status_code == 200
    assert first_response.json() == second_response.json()


def test_ask_returns_answer_with_citations_using_mock_llm(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Ask")
    project_id = project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="ask.txt",
        content=b"alpha answer source",
    )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What does alpha say?", "retrieval_limit": 1},
        headers=_auth_headers(),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "answered"
    assert body["answer"]
    assert body["citations"][0]["citation_id"] == "[1]"
    assert body["sources"][0]["source_reference"]["citation_id"] == "[1]"
    assert body["used_context"] is None


def test_ask_with_empty_retrieval_returns_insufficient_context(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Empty ask")

    response = documents_client.client.post(
        f"/api/v1/projects/{project.json()['id']}/ask",
        json={"question": "What is missing?", "include_context": True},
        headers=_auth_headers(),
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "insufficient_context"
    assert body["answer"] == "I could not find enough information in the provided documents."
    assert body["citations"] == []
    assert body["sources"] == []
    assert body["used_context"] == ""


def test_ask_foreign_project_and_unauthenticated(
    documents_client: DocumentsClient,
) -> None:
    foreign_project = _create_project(
        documents_client.client,
        name="Foreign ask",
        token="user-two",
    )

    unauthenticated_response = documents_client.client.post(
        f"/api/v1/projects/{foreign_project.json()['id']}/ask",
        json={"question": "Any answer?"},
    )
    foreign_response = documents_client.client.post(
        f"/api/v1/projects/{foreign_project.json()['id']}/ask",
        json={"question": "Any answer?"},
        headers=_auth_headers(),
    )

    assert unauthenticated_response.status_code == 401
    assert foreign_response.status_code == 404


def test_ask_provider_unavailable_returns_failed_status(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Unavailable ask")
    project_id = project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="unavailable-ask.txt",
        content=b"alpha unavailable provider",
    )
    bad_service = RagAnswerService(
        project_retriever=_build_project_retriever(documents_client),
        llm_provider=UnavailableLLMProvider(),
        prompt_builder=PromptBuilder(),
    )
    documents_client.client.app.dependency_overrides[get_rag_answer_service] = (
        lambda: bad_service
    )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What about alpha?"},
        headers=_auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_prompt_builder_includes_citations_and_grounding_rules() -> None:
    source = _build_source_reference(project_id=uuid4(), index=1)

    prompt = PromptBuilder().build_prompt(
        question="What is alpha?",
        context="[1] Alpha context",
        citations=[source],
    )

    assert "[1]" in prompt
    assert "Do not invent facts" in prompt
    assert "untrusted content" in prompt
    assert "ignore" in prompt.lower()


def test_ask_does_not_leak_other_project_or_user_chunks(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Scoped ask")
    other_project = _create_project(documents_client.client, name="Other ask")
    foreign_project = _create_project(
        documents_client.client,
        name="Foreign scoped ask",
        token="user-two",
    )
    project_id = project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="ask-own.txt",
        content=b"shared alpha owned context",
    )
    _upload_process_embed_and_attach(
        documents_client,
        project_id=other_project.json()["id"],
        filename="ask-other.txt",
        content=b"shared alpha other project context",
    )
    _upload_process_embed_and_attach(
        documents_client,
        project_id=foreign_project.json()["id"],
        filename="ask-foreign.txt",
        content=b"shared alpha foreign context",
        token="user-two",
    )

    response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "shared alpha", "include_context": True, "retrieval_limit": 10},
        headers=_auth_headers(),
    )

    body = response.json()
    assert response.status_code == 200
    assert "ask-own" in body["used_context"]
    assert "other project" not in body["used_context"]
    assert "foreign" not in body["used_context"]


def test_ask_include_context_flag_controls_used_context(
    documents_client: DocumentsClient,
) -> None:
    project = _create_project(documents_client.client, name="Context flag ask")
    project_id = project.json()["id"]
    _upload_process_embed_and_attach(
        documents_client,
        project_id=project_id,
        filename="context-flag.txt",
        content=b"alpha context flag",
    )

    hidden_response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "alpha", "include_context": False},
        headers=_auth_headers(),
    )
    visible_response = documents_client.client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "alpha", "include_context": True},
        headers=_auth_headers(),
    )

    assert hidden_response.status_code == 200
    assert hidden_response.json()["used_context"] is None
    assert visible_response.status_code == 200
    assert visible_response.json()["used_context"]


def test_llm_provider_registry_and_mock_are_deterministic() -> None:
    registry = LLMProviderRegistry(
        provider_name="mock",
        model_name="mock",
        openai_api_key=None,
    )
    provider = registry.get_provider()

    assert provider.provider_name == "mock"
    with pytest.raises(LLMProviderError):
        LLMProviderRegistry(
            provider_name="unsupported",
            model_name="mock",
            openai_api_key=None,
        ).get_provider()


@pytest.mark.asyncio
async def test_mock_llm_provider_deterministic_output() -> None:
    provider = MockLLMProvider(model_name="mock")

    first = await provider.generate_answer(
        prompt="prompt",
        question="What is alpha?",
        context="[1] Alpha",
    )
    second = await provider.generate_answer(
        prompt="prompt",
        question="What is alpha?",
        context="[1] Alpha",
    )

    assert first == second


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
        chunking_strategy=FixedSizeChunkingStrategy(
            chunk_size_chars=10,
            chunk_overlap_chars=2,
        ),
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


class WrongDimensionsProvider:
    provider_name = "wrong"
    model_name = "wrong"
    dimensions = 4

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        return [
            EmbeddingResult(vector=[1.0, 0.0, 0.0, 0.0], provider="wrong", model="wrong")
            for _ in texts
        ]


class PartiallyFailingProvider:
    provider_name = "partial"
    model_name = "partial"
    dimensions = 8

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        text = texts[0]
        if "bad" in text:
            raise EmbeddingProviderError("partial failure")
        return await MockEmbeddingProvider(model_name="partial", dimensions=8).embed_texts(texts)


class UnavailableProvider:
    provider_name = "unavailable"
    model_name = "unavailable"
    dimensions = 8

    async def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        raise EmbeddingProviderError("provider unavailable")


class UnavailableLLMProvider:
    provider_name = "unavailable"
    model_name = "unavailable"

    async def generate_answer(self, *, prompt: str, question: str, context: str) -> LLMResult:
        raise LLMProviderError("provider unavailable")


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


def _build_project_retriever(documents_client: DocumentsClient) -> ProjectRetriever:
    return ProjectRetriever(  # type: ignore[arg-type]
        project_repository=documents_client.project_repository,
        document_repository=documents_client.document_repository,
        embedding_provider=MockEmbeddingProvider(
            model_name="mock-embedding",
            dimensions=8,
        ),
        embedding_dimensions=8,
        context_builder=ContextBuilder(max_chars=500),
        default_limit=5,
        max_limit=3,
    )


def _build_upload_file(*, filename: str, content: bytes, content_type: str) -> UploadFile:
    file = SpooledTemporaryFile()
    file.write(content)
    file.seek(0)
    return UploadFile(file=file, filename=filename, headers=Headers({"content-type": content_type}))


def _upload_process_and_embed(
    documents_client: DocumentsClient,
    *,
    content: bytes,
    filename: str = "embedding.txt",
    token: str = "user-one",
) -> str:
    upload_response = _upload_document(
        documents_client.client,
        filename=filename,
        content=content,
        content_type="text/plain",
        token=token,
    )
    document_id = upload_response.json()["document"]["id"]
    documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(token),
    )
    documents_client.client.post(
        f"/api/v1/documents/{document_id}/embed",
        headers=_auth_headers(token),
    )
    return document_id


def _upload_process_embed_and_attach(
    documents_client: DocumentsClient,
    *,
    project_id: str,
    content: bytes,
    filename: str,
    token: str = "user-one",
) -> str:
    upload_response = _upload_document(
        documents_client.client,
        filename=filename,
        content=content,
        content_type="text/plain",
        token=token,
        project_id=project_id,
    )
    document_id = upload_response.json()["document"]["id"]
    documents_client.client.post(
        f"/api/v1/documents/{document_id}/process",
        headers=_auth_headers(token),
    )
    documents_client.client.post(
        f"/api/v1/documents/{document_id}/embed",
        headers=_auth_headers(token),
    )
    return document_id


def _build_source_reference(*, project_id: UUID, index: int) -> SourceReference:
    return SourceReference(
        citation_id=f"[{index}]",
        document_id=project_id,
        document_title="Document",
        chunk_id=uuid4(),
        chunk_index=index - 1,
        source_url=None,
        page_number=None,
        start_offset=0,
        end_offset=100,
    )


def _build_retrieval_result(
    *,
    project_id: UUID,
    source: SourceReference,
    text: str,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=source.chunk_id,
        document_id=project_id,
        document_title=source.document_title,
        chunk_index=source.chunk_index,
        text=text,
        similarity_score=1.0,
        source_reference=source,
        metadata={},
    )


async def _build_processed_document_for_embedding_test(
    tmp_path: Path,
    *,
    content: bytes = b"good chunk",
) -> tuple[InMemoryDocumentRepository, Document]:
    project_repository = InMemoryProjectRepository()
    document_repository = InMemoryDocumentRepository()
    storage_service = _build_storage_service(tmp_path)
    document_service = DocumentService(  # type: ignore[arg-type]
        document_repository=document_repository,
        project_repository=project_repository,
    )
    processing_service = DocumentProcessingService(  # type: ignore[arg-type]
        document_repository=document_repository,
        parser_registry=ParserRegistry(),
        chunking_strategy=FixedSizeChunkingStrategy(
            chunk_size_chars=10,
            chunk_overlap_chars=0,
        ),
        storage_service=storage_service,
        max_extracted_text_chars=10_000,
    )
    owner_id = uuid4()
    document, _ = await document_service.upload_document(
        owner_id=owner_id,
        upload_file=_build_upload_file(
            filename="embedding.txt",
            content=content,
            content_type="text/plain",
        ),
        storage_service=storage_service,
        project_id=None,
    )
    document = await processing_service.process_document(
        document_id=document.id,
        owner_id=owner_id,
    )
    return document_repository, document


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(
        left_value * right_value for left_value, right_value in zip(left, right, strict=True)
    )
    left_magnitude = sum(value * value for value in left) ** 0.5
    right_magnitude = sum(value * value for value in right) ** 0.5
    if left_magnitude == 0 or right_magnitude == 0:
        return 0.0
    return numerator / (left_magnitude * right_magnitude)
