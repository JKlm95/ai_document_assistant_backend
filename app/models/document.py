from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document_chunk import DocumentChunk
    from app.models.project import Project
    from app.models.user import User


class DocumentProcessingStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PARSED = "parsed"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    READY = "ready"
    FAILED = "failed"


class DocumentClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"


class DocumentProcessingMode(StrEnum):
    LOCAL_ONLY = "local_only"
    EXTERNAL_ALLOWED = "external_allowed"
    PREFER_LOCAL = "prefer_local"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_id_updated_at", "owner_id", "updated_at"),
        Index("ix_documents_owner_id_processing_status", "owner_id", "processing_status"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_provider: Mapped[str] = mapped_column(
        String(50),
        default="local",
        server_default="local",
        nullable=False,
    )
    processing_status: Mapped[DocumentProcessingStatus] = mapped_column(
        Enum(
            DocumentProcessingStatus,
            name="document_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=DocumentProcessingStatus.UPLOADED,
        server_default=DocumentProcessingStatus.UPLOADED.value,
        nullable=False,
    )
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_extension: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text_length: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    chunked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    classification: Mapped[DocumentClassification] = mapped_column(
        Enum(
            DocumentClassification,
            name="document_classification",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=DocumentClassification.INTERNAL,
        server_default=DocumentClassification.INTERNAL.value,
        nullable=False,
    )
    processing_mode: Mapped[DocumentProcessingMode] = mapped_column(
        Enum(
            DocumentProcessingMode,
            name="document_processing_mode",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=DocumentProcessingMode.PREFER_LOCAL,
        server_default=DocumentProcessingMode.PREFER_LOCAL.value,
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    document_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    owner: Mapped[User] = relationship(back_populates="documents")
    project_documents: Mapped[list[ProjectDocument]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class ProjectDocument(CreatedAtMixin, Base):
    __tablename__ = "project_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "document_id", name="uq_project_documents_project_document"),
        Index("ix_project_documents_document_id", "document_id"),
    )

    project_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )

    project: Mapped[Project] = relationship(back_populates="project_documents")
    document: Mapped[Document] = relationship(back_populates="project_documents")
