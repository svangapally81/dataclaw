"""unified agent fields

Revision ID: 0012_unified_agents
Revises: 0011_monitoring
Create Date: 2026-05-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0012_unified_agents"
down_revision = "0011_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(length=40), nullable=False, server_default="on_demand"))
        batch_op.add_column(sa.Column("sql_query", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("cadence_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("thresholds", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch_op.add_column(sa.Column("uses_llm_filter", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("target_connector_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_agents_kind", ["kind"])
        batch_op.create_foreign_key(
            "fk_agents_target_connector_id_connectors",
            "connectors",
            ["target_connector_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_constraint("fk_agents_target_connector_id_connectors", type_="foreignkey")
        batch_op.drop_index("ix_agents_kind")
        batch_op.drop_column("target_connector_id")
        batch_op.drop_column("uses_llm_filter")
        batch_op.drop_column("thresholds")
        batch_op.drop_column("cadence_minutes")
        batch_op.drop_column("kind")
        batch_op.drop_column("sql_query")
