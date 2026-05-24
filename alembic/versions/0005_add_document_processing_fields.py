"""add document processing fields

Revision ID: 0005_add_document_processing_fields
Revises: 0004_add_document_upload_storage_fields
Create Date: 2026-05-24 21:53:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_add_document_processing_fields"
down_revision: str | None = "0004_add_document_upload_storage_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("extracted_text_length", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("documents", sa.Column("processing_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "processing_error")
    op.drop_column("documents", "processed_at")
    op.drop_column("documents", "extracted_text_length")
    op.drop_column("documents", "extracted_text")
