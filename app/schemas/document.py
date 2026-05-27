from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import (
    DocumentClassification,
    DocumentProcessingMode,
    DocumentProcessingStatus,
)
from app.models.document_chunk import ChunkEmbeddingStatus


class DocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size_bytes: int = Field(ge=0)
    storage_provider: str = Field(default="local", min_length=1, max_length=50)
    content_hash: str | None = Field(default=None, max_length=64)
    classification: DocumentClassification = DocumentClassification.INTERNAL
    processing_mode: DocumentProcessingMode = DocumentProcessingMode.PREFER_LOCAL
    language: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=2)
    document_type: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None
    source_url: str | None = Field(default=None, max_length=1000)
    version: str | None = Field(default=None, max_length=50)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    title: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    storage_provider: str
    storage_path: str | None
    file_extension: str | None
    processing_status: DocumentProcessingStatus
    content_hash: str | None
    uploaded_at: datetime | None
    extracted_text_length: int | None
    processed_at: datetime | None
    processing_error: str | None
    chunk_count: int
    chunked_at: datetime | None
    classification: DocumentClassification
    processing_mode: DocumentProcessingMode
    language: str | None
    country: str | None
    document_type: str | None
    tags: list[str] | None
    source_url: str | None
    version: str | None
    created_at: datetime
    updated_at: datetime


class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    chunk_index: int
    text: str
    char_count: int
    token_count_estimate: int
    start_offset: int
    end_offset: int
    embedding_provider: str | None
    embedding_model: str | None
    embedded_at: datetime | None
    embedding_error: str | None
    embedding_status: ChunkEmbeddingStatus
    embedding_dimensions: int | None
    created_at: datetime


class DocumentContentResponse(BaseModel):
    document: DocumentResponse
    extracted_text: str | None
    extracted_text_length: int | None


class DocumentChunksResponse(BaseModel):
    document: DocumentResponse
    chunks: list[DocumentChunkResponse]
    chunk_count: int


class DocumentEmbeddingStatusResponse(BaseModel):
    document: DocumentResponse
    total_chunks: int
    pending_chunks: int
    embedded_chunks: int
    failed_chunks: int


class SimilarChunkResponse(BaseModel):
    document_id: UUID
    chunk_id: UUID
    chunk_index: int
    text: str
    similarity_score: float
    embedding_provider: str | None
    embedding_model: str | None


class SimilarChunksResponse(BaseModel):
    query: str
    items: list[SimilarChunkResponse]
    limit: int


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    linked_project_id: UUID | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int
