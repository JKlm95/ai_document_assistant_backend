"""add project archived flag

Revision ID: 0002_add_project_archived_flag
Revises: 0001_initial_empty_migration
Create Date: 2026-05-24 21:12:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_add_project_archived_flag"
down_revision: str | None = "0001_initial_empty_migration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("is_archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index(
        "ix_projects_user_id_is_archived_updated_at",
        "projects",
        ["user_id", "is_archived", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_projects_user_id_is_archived_updated_at", table_name="projects")
    op.drop_column("projects", "is_archived")
