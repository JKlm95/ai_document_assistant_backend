"""add document chunking foundation

Revision ID: 0006_add_document_chunking_foundation
Revises: 0005_add_document_processing_fields
Create Date: 2026-05-24 21:59:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_add_document_chunking_foundation"
down_revision: str | None = "0005_add_document_processing_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'parsed'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'chunked'")

    op.add_column(
        "documents",
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("documents", sa.Column("chunked_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("document_chunks", sa.Column("text", sa.Text(), nullable=True))
    op.add_column("document_chunks", sa.Column("char_count", sa.Integer(), nullable=True))
    op.add_column(
        "document_chunks",
        sa.Column("token_count_estimate", sa.Integer(), nullable=True),
    )
    op.add_column("document_chunks", sa.Column("start_offset", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("end_offset", sa.Integer(), nullable=True))

    op.execute("UPDATE document_chunks SET text = content")
    op.execute("UPDATE document_chunks SET char_count = length(text)")
    op.execute("UPDATE document_chunks SET token_count_estimate = COALESCE(token_count, 0)")
    op.execute("UPDATE document_chunks SET start_offset = 0")
    op.execute("UPDATE document_chunks SET end_offset = char_count")

    op.alter_column("document_chunks", "text", nullable=False)
    op.alter_column("document_chunks", "char_count", nullable=False)
    op.alter_column("document_chunks", "token_count_estimate", nullable=False)
    op.alter_column("document_chunks", "start_offset", nullable=False)
    op.alter_column("document_chunks", "end_offset", nullable=False)

    op.drop_column("document_chunks", "chunk_metadata")
    op.drop_column("document_chunks", "embedding")
    op.drop_column("document_chunks", "token_count")
    op.drop_column("document_chunks", "content")


def downgrade() -> None:
    op.add_column("document_chunks", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("document_chunks", sa.Column("token_count", sa.Integer(), nullable=True))
    op.add_column("document_chunks", sa.Column("embedding", Vector(768), nullable=True))
    op.add_column(
        "document_chunks",
        sa.Column("chunk_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.execute("UPDATE document_chunks SET content = text")
    op.execute("UPDATE document_chunks SET token_count = token_count_estimate")
    op.alter_column("document_chunks", "content", nullable=False)

    op.drop_column("document_chunks", "end_offset")
    op.drop_column("document_chunks", "start_offset")
    op.drop_column("document_chunks", "token_count_estimate")
    op.drop_column("document_chunks", "char_count")
    op.drop_column("document_chunks", "text")

    op.drop_column("documents", "chunked_at")
    op.drop_column("documents", "chunk_count")
