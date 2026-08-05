"""knowledge node source attribution

Revision ID: 0014_knowledge_node_source
Revises: 0013_runtime_foundation
Create Date: 2026-05-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_knowledge_node_source"
down_revision = "0013_runtime_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_nodes") as batch_op:
        batch_op.drop_constraint("uq_knowledge_nodes_identity", type_="unique")
        batch_op.add_column(sa.Column("connector_slug", sa.String(length=80), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("source_type", sa.String(length=80), nullable=False, server_default="unknown"))
        batch_op.add_column(sa.Column("summary", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("summary_embedded_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_unique_constraint(
            "uq_knowledge_nodes_identity",
            ["workspace_id", "type", "canonical_name", "connector_slug"],
        )

    op.execute(
        """
        UPDATE knowledge_nodes
        SET connector_slug = COALESCE(
                (SELECT wiki_pages.source_type FROM wiki_pages WHERE wiki_pages.id = knowledge_nodes.primary_wiki_page_id),
                'unknown'
            ),
            source_type = COALESCE(
                (SELECT wiki_pages.source_type FROM wiki_pages WHERE wiki_pages.id = knowledge_nodes.primary_wiki_page_id),
                'unknown'
            )
        """
    )
    op.execute(
        """
        UPDATE knowledge_nodes
        SET summary = type || ' ' || canonical_name || ' from ' || connector_slug || '.'
        WHERE summary = ''
        """
    )

    op.create_index("ix_knowledge_nodes_connector_slug", "knowledge_nodes", ["connector_slug"])
    op.create_index("ix_knowledge_nodes_source_type", "knowledge_nodes", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_nodes_source_type", table_name="knowledge_nodes")
    op.drop_index("ix_knowledge_nodes_connector_slug", table_name="knowledge_nodes")
    with op.batch_alter_table("knowledge_nodes") as batch_op:
        batch_op.drop_constraint("uq_knowledge_nodes_identity", type_="unique")
        batch_op.drop_column("summary_embedded_at")
        batch_op.drop_column("summary")
        batch_op.drop_column("source_type")
        batch_op.drop_column("connector_slug")
        batch_op.create_unique_constraint(
            "uq_knowledge_nodes_identity",
            ["workspace_id", "type", "canonical_name"],
        )
