from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document


class ChunkEmbeddingStatus(StrEnum):
    PENDING = "pending"
    EMBEDDED = "embedded"
    FAILED = "failed"


class DocumentChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_index"),
        Index(
            "ix_document_chunks_embedding_status",
            "document_id",
            "embedding_status",
        ),
    )

    document_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_status: Mapped[ChunkEmbeddingStatus] = mapped_column(
        Enum(
            ChunkEmbeddingStatus,
            name="chunk_embedding_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=ChunkEmbeddingStatus.PENDING,
        server_default=ChunkEmbeddingStatus.PENDING.value,
        nullable=False,
    )
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding_vector: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")
