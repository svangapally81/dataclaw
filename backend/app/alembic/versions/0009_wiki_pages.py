"""wiki pages

Revision ID: 0009_wiki_pages
Revises: 0008_agent_write_audit
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_wiki_pages"
down_revision: str | None = "0008_agent_write_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wiki_pages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("disk_path", sa.String(1000), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("frontmatter", sa.JSON(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("disk_mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "path", name="uq_wiki_pages_workspace_path"),
    )
    op.create_index("ix_wiki_pages_workspace_id", "wiki_pages", ["workspace_id"])
    op.create_index("ix_wiki_pages_path", "wiki_pages", ["path"])
    op.create_index("ix_wiki_pages_tier", "wiki_pages", ["tier"])
    op.create_index("ix_wiki_pages_source_type", "wiki_pages", ["source_type"])
    op.create_index("ix_wiki_pages_source_id", "wiki_pages", ["source_id"])
    op.create_index("ix_wiki_pages_content_hash", "wiki_pages", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_wiki_pages_content_hash", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_source_id", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_source_type", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_tier", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_path", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_workspace_id", table_name="wiki_pages")
    op.drop_table("wiki_pages")
