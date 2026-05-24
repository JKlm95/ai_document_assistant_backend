from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentProcessingStatus


class DocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    file_size_bytes: int = Field(ge=0)
    storage_provider: str = Field(default="local", min_length=1, max_length=50)
    content_hash: str | None = Field(default=None, max_length=64)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    title: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    storage_provider: str
    processing_status: DocumentProcessingStatus
    content_hash: str | None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int
