"""agent write audit

Revision ID: 0008_agent_write_audit
Revises: 0007_chat_chart_spec
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_agent_write_audit"
down_revision: str | None = "0007_chat_chart_spec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_write_audit",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("connector_slug", sa.String(80), nullable=False),
        sa.Column("statement_type", sa.String(80), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("affected_rows", sa.Integer(), nullable=True),
        sa.Column("required_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("alert_id", sa.String(), sa.ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_by", sa.String(255), nullable=True),
    )
    op.create_index("ix_agent_write_audit_workspace_id", "agent_write_audit", ["workspace_id"])
    op.create_index("ix_agent_write_audit_agent_id", "agent_write_audit", ["agent_id"])
    op.create_index("ix_agent_write_audit_connector_slug", "agent_write_audit", ["connector_slug"])
    op.create_index("ix_agent_write_audit_executed_at", "agent_write_audit", ["executed_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_write_audit_executed_at", table_name="agent_write_audit")
    op.drop_index("ix_agent_write_audit_connector_slug", table_name="agent_write_audit")
    op.drop_index("ix_agent_write_audit_agent_id", table_name="agent_write_audit")
    op.drop_index("ix_agent_write_audit_workspace_id", table_name="agent_write_audit")
    op.drop_table("agent_write_audit")
