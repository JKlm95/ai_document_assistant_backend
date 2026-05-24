"""document metadata foundation

Revision ID: 0003_document_metadata_foundation
Revises: 0002_add_project_archived_flag
Create Date: 2026-05-24 21:21:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_document_metadata_foundation"
down_revision: str | None = "0002_add_project_archived_flag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_documents_user_id_status", table_name="documents")
    op.drop_index("ix_documents_user_id", table_name="documents")

    op.add_column("documents", sa.Column("title", sa.String(length=255), nullable=True))
    op.execute("UPDATE documents SET title = filename")
    op.alter_column("documents", "title", nullable=False)

    op.alter_column("documents", "user_id", new_column_name="owner_id")
    op.alter_column("documents", "filename", new_column_name="original_filename")
    op.alter_column("documents", "content_type", new_column_name="mime_type")
    op.alter_column("documents", "status", new_column_name="processing_status")
    op.alter_column("documents", "file_size", new_column_name="file_size_bytes")

    op.drop_column("documents", "storage_path")
    op.drop_column("documents", "error_message")

    op.create_index("ix_documents_owner_id", "documents", ["owner_id"], unique=False)
    op.create_index(
        "ix_documents_owner_id_updated_at",
        "documents",
        ["owner_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_documents_owner_id_processing_status",
        "documents",
        ["owner_id", "processing_status"],
        unique=False,
    )
    op.create_index(
        "ix_project_documents_document_id",
        "project_documents",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_project_documents_document_id", table_name="project_documents")
    op.drop_index("ix_documents_owner_id_processing_status", table_name="documents")
    op.drop_index("ix_documents_owner_id_updated_at", table_name="documents")
    op.drop_index("ix_documents_owner_id", table_name="documents")

    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column("storage_path", sa.String(length=500), server_default="", nullable=False),
    )
    op.alter_column("documents", "storage_path", server_default=None)

    op.alter_column("documents", "file_size_bytes", new_column_name="file_size")
    op.alter_column("documents", "processing_status", new_column_name="status")
    op.alter_column("documents", "mime_type", new_column_name="content_type")
    op.alter_column("documents", "original_filename", new_column_name="filename")
    op.alter_column("documents", "owner_id", new_column_name="user_id")

    op.drop_column("documents", "title")

    op.create_index("ix_documents_user_id", "documents", ["user_id"], unique=False)
    op.create_index(
        "ix_documents_user_id_status",
        "documents",
        ["user_id", "status"],
        unique=False,
    )
