"""knowledge graph

Revision ID: 0010_knowledge_graph
Revises: 0009_wiki_pages
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_knowledge_graph"
down_revision: str | None = "0009_wiki_pages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("primary_wiki_page_id", sa.String(), sa.ForeignKey("wiki_pages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("compile_run_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "type", "canonical_name", name="uq_knowledge_nodes_identity"),
    )
    op.create_index("ix_knowledge_nodes_workspace_id", "knowledge_nodes", ["workspace_id"])
    op.create_index("ix_knowledge_nodes_type", "knowledge_nodes", ["type"])
    op.create_index("ix_knowledge_nodes_canonical_name", "knowledge_nodes", ["canonical_name"])
    op.create_index("ix_knowledge_nodes_compile_run_id", "knowledge_nodes", ["compile_run_id"])

    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("src_node_id", sa.String(), sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dst_node_id", sa.String(), sa.ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship", sa.String(80), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("compile_run_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "src_node_id",
            "dst_node_id",
            "relationship",
            "source",
            name="uq_knowledge_edges_identity",
        ),
    )
    op.create_index("ix_knowledge_edges_workspace_id", "knowledge_edges", ["workspace_id"])
    op.create_index("ix_knowledge_edges_src_node_id", "knowledge_edges", ["src_node_id"])
    op.create_index("ix_knowledge_edges_dst_node_id", "knowledge_edges", ["dst_node_id"])
    op.create_index("ix_knowledge_edges_relationship", "knowledge_edges", ["relationship"])
    op.create_index("ix_knowledge_edges_source", "knowledge_edges", ["source"])
    op.create_index("ix_knowledge_edges_compile_run_id", "knowledge_edges", ["compile_run_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_edges_compile_run_id", table_name="knowledge_edges")
    op.drop_index("ix_knowledge_edges_source", table_name="knowledge_edges")
    op.drop_index("ix_knowledge_edges_relationship", table_name="knowledge_edges")
    op.drop_index("ix_knowledge_edges_dst_node_id", table_name="knowledge_edges")
    op.drop_index("ix_knowledge_edges_src_node_id", table_name="knowledge_edges")
    op.drop_index("ix_knowledge_edges_workspace_id", table_name="knowledge_edges")
    op.drop_table("knowledge_edges")
    op.drop_index("ix_knowledge_nodes_compile_run_id", table_name="knowledge_nodes")
    op.drop_index("ix_knowledge_nodes_canonical_name", table_name="knowledge_nodes")
    op.drop_index("ix_knowledge_nodes_type", table_name="knowledge_nodes")
    op.drop_index("ix_knowledge_nodes_workspace_id", table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")
