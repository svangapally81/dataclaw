"""monitoring agents

Revision ID: 0011_monitoring
Revises: 0010_knowledge_graph
Create Date: 2026-05-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_monitoring"
down_revision: str | None = "0010_knowledge_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.add_column(sa.Column("fingerprint", sa.String(255), nullable=True))
        batch_op.create_index("ix_alerts_fingerprint", ["fingerprint"])

    op.create_table(
        "monitoring_configs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("agent_name", sa.String(120), nullable=False),
        sa.Column("connector_id", sa.String(), sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("notification_channels", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "agent_name",
            "connector_id",
            name="uq_monitoring_configs_scope",
        ),
    )
    op.create_index("ix_monitoring_configs_workspace_id", "monitoring_configs", ["workspace_id"])
    op.create_index("ix_monitoring_configs_agent_name", "monitoring_configs", ["agent_name"])
    op.create_index("ix_monitoring_configs_connector_id", "monitoring_configs", ["connector_id"])

    op.create_table(
        "query_audit",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("connector_slug", sa.String(80), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("rows_returned", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_query_audit_workspace_id", "query_audit", ["workspace_id"])
    op.create_index("ix_query_audit_connector_slug", "query_audit", ["connector_slug"])
    op.create_index("ix_query_audit_executed_at", "query_audit", ["executed_at"])

    op.create_table(
        "worker_heartbeat",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("worker_name", sa.String(120), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.UniqueConstraint("worker_name", name="uq_worker_heartbeat_name"),
    )
    op.create_index("ix_worker_heartbeat_worker_name", "worker_heartbeat", ["worker_name"])
    op.create_index("ix_worker_heartbeat_last_seen_at", "worker_heartbeat", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeat_last_seen_at", table_name="worker_heartbeat")
    op.drop_index("ix_worker_heartbeat_worker_name", table_name="worker_heartbeat")
    op.drop_table("worker_heartbeat")
    op.drop_index("ix_query_audit_executed_at", table_name="query_audit")
    op.drop_index("ix_query_audit_connector_slug", table_name="query_audit")
    op.drop_index("ix_query_audit_workspace_id", table_name="query_audit")
    op.drop_table("query_audit")
    op.drop_index("ix_monitoring_configs_connector_id", table_name="monitoring_configs")
    op.drop_index("ix_monitoring_configs_agent_name", table_name="monitoring_configs")
    op.drop_index("ix_monitoring_configs_workspace_id", table_name="monitoring_configs")
    op.drop_table("monitoring_configs")
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.drop_index("ix_alerts_fingerprint")
        batch_op.drop_column("fingerprint")
