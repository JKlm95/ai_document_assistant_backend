"""add document upload storage fields

Revision ID: 0004_add_document_upload_storage_fields
Revises: 0003_document_metadata_foundation
Create Date: 2026-05-24 21:33:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_add_document_upload_storage_fields"
down_revision: str | None = "0003_document_metadata_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("storage_path", sa.String(length=500), nullable=True))
    op.add_column("documents", sa.Column("file_extension", sa.String(length=20), nullable=True))
    op.add_column("documents", sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("ALTER TYPE document_status RENAME VALUE 'processed' TO 'ready'")


def downgrade() -> None:
    op.execute("ALTER TYPE document_status RENAME VALUE 'ready' TO 'processed'")
    op.drop_column("documents", "uploaded_at")
    op.drop_column("documents", "file_extension")
    op.drop_column("documents", "storage_path")
