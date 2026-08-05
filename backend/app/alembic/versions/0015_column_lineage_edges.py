"""column lineage edges

Revision ID: 0015_column_lineage_edges
Revises: 0014_knowledge_node_source
Create Date: 2026-05-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_column_lineage_edges"
down_revision = "0014_knowledge_node_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "column_lineage_edges",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("source_connector_slug", sa.String(length=80), nullable=False),
        sa.Column("source_table", sa.String(length=255), nullable=False),
        sa.Column("source_column", sa.String(length=255), nullable=False),
        sa.Column("target_connector_slug", sa.String(length=80), nullable=False),
        sa.Column("target_table", sa.String(length=255), nullable=False),
        sa.Column("target_column", sa.String(length=255), nullable=False),
        sa.Column("relationship", sa.String(length=120), nullable=False, server_default="derives_from"),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_page_id", sa.String(), nullable=True),
        sa.Column("compile_run_id", sa.String(length=80), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_page_id"], ["wiki_pages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "source_connector_slug",
            "source_table",
            "source_column",
            "target_connector_slug",
            "target_table",
            "target_column",
            "relationship",
            name="uq_column_lineage_edges_identity",
        ),
    )
    for column in (
        "workspace_id",
        "source_connector_slug",
        "source_table",
        "source_column",
        "target_connector_slug",
        "target_table",
        "target_column",
        "relationship",
        "source_page_id",
        "compile_run_id",
    ):
        op.create_index(f"ix_column_lineage_edges_{column}", "column_lineage_edges", [column])


def downgrade() -> None:
    for column in (
        "compile_run_id",
        "source_page_id",
        "relationship",
        "target_column",
        "target_table",
        "target_connector_slug",
        "source_column",
        "source_table",
        "source_connector_slug",
        "workspace_id",
    ):
        op.drop_index(f"ix_column_lineage_edges_{column}", table_name="column_lineage_edges")
    op.drop_table("column_lineage_edges")
