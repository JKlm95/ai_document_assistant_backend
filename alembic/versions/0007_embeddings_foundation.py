"""add embeddings foundation

Revision ID: 0007_embeddings_foundation
Revises: 0006_add_document_chunking_foundation
Create Date: 2026-05-27 18:41:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_embeddings_foundation"
down_revision: str | None = "0006_add_document_chunking_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

chunk_embedding_status = postgresql.ENUM(
    "pending",
    "embedded",
    "failed",
    name="chunk_embedding_status",
)
document_classification = postgresql.ENUM(
    "public",
    "internal",
    "confidential",
    name="document_classification",
)
document_processing_mode = postgresql.ENUM(
    "local_only",
    "external_allowed",
    "prefer_local",
    name="document_processing_mode",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'embedded'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'indexed'")

    bind = op.get_bind()
    chunk_embedding_status.create(bind, checkfirst=True)
    document_classification.create(bind, checkfirst=True)
    document_processing_mode.create(bind, checkfirst=True)

    op.add_column(
        "documents",
        sa.Column(
            "classification",
            document_classification,
            server_default="internal",
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "processing_mode",
            document_processing_mode,
            server_default="prefer_local",
            nullable=False,
        ),
    )
    op.add_column("documents", sa.Column("language", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("country", sa.String(length=2), nullable=True))
    op.add_column("documents", sa.Column("document_type", sa.String(length=100), nullable=True))
    op.add_column(
        "documents",
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("documents", sa.Column("source_url", sa.String(length=1000), nullable=True))
    op.add_column("documents", sa.Column("version", sa.String(length=50), nullable=True))

    op.add_column(
        "document_chunks",
        sa.Column("embedding_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_model", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("document_chunks", sa.Column("embedding_error", sa.Text(), nullable=True))
    op.add_column(
        "document_chunks",
        sa.Column(
            "embedding_status",
            chunk_embedding_status,
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column("document_chunks", sa.Column("embedding_dimensions", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding_vector", Vector(768), nullable=True))
    op.create_index(
        "ix_document_chunks_embedding_status",
        "document_chunks",
        ["document_id", "embedding_status"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_vector_hnsw "
        "ON document_chunks USING hnsw (embedding_vector vector_cosine_ops) "
        "WHERE embedding_vector IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_vector_hnsw")
    op.drop_index("ix_document_chunks_embedding_status", table_name="document_chunks")
    op.drop_column("document_chunks", "embedding_vector")
    op.drop_column("document_chunks", "embedding_dimensions")
    op.drop_column("document_chunks", "embedding_status")
    op.drop_column("document_chunks", "embedding_error")
    op.drop_column("document_chunks", "embedded_at")
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding_provider")

    op.drop_column("documents", "version")
    op.drop_column("documents", "source_url")
    op.drop_column("documents", "tags")
    op.drop_column("documents", "document_type")
    op.drop_column("documents", "country")
    op.drop_column("documents", "language")
    op.drop_column("documents", "processing_mode")
    op.drop_column("documents", "classification")

    document_processing_mode.drop(op.get_bind(), checkfirst=True)
    document_classification.drop(op.get_bind(), checkfirst=True)
    chunk_embedding_status.drop(op.get_bind(), checkfirst=True)
