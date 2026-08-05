"""runtime foundation

Revision ID: 0013_runtime_foundation
Revises: 0012_unified_agents
Create Date: 2026-05-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0013_runtime_foundation"
down_revision = "0012_unified_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(sa.Column("force_run_requested_at", sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("duration_ms", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("state", sa.String(length=40), nullable=False, server_default="completed"))
        batch_op.add_column(sa.Column("lease_token", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("budget_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("budget_seconds", sa.Integer(), nullable=True))
        batch_op.create_index("ix_agent_runs_state", ["state"])
        batch_op.create_index("ix_agent_runs_lease_token", ["lease_token"])
        batch_op.create_index("ix_agent_runs_lease_expires_at", ["lease_expires_at"])
        batch_op.create_unique_constraint("uq_agent_runs_idempotency_key", ["idempotency_key"])

    op.create_table(
        "agent_tool_call",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("agent_name", sa.String(length=120), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("connector_slug", sa.String(length=80), nullable=True),
        sa.Column("args_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("result_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="ok"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_tool_call_run_id", "agent_tool_call", ["run_id"])
    op.create_index("ix_agent_tool_call_agent_name", "agent_tool_call", ["agent_name"])
    op.create_index("ix_agent_tool_call_tool_name", "agent_tool_call", ["tool_name"])
    op.create_index("ix_agent_tool_call_connector_slug", "agent_tool_call", ["connector_slug"])
    op.create_index("ix_agent_tool_call_status", "agent_tool_call", ["status"])
    op.create_index("ix_agent_tool_call_called_at", "agent_tool_call", ["called_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_tool_call_called_at", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_status", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_connector_slug", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_tool_name", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_agent_name", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_run_id", table_name="agent_tool_call")
    op.drop_table("agent_tool_call")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint("uq_agent_runs_idempotency_key", type_="unique")
        batch_op.drop_index("ix_agent_runs_lease_expires_at")
        batch_op.drop_index("ix_agent_runs_lease_token")
        batch_op.drop_index("ix_agent_runs_state")
        batch_op.drop_column("budget_seconds")
        batch_op.drop_column("budget_tokens")
        batch_op.drop_column("idempotency_key")
        batch_op.drop_column("retry_count")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_token")
        batch_op.drop_column("state")
        batch_op.drop_column("error_message")
        batch_op.drop_column("duration_ms")
        batch_op.drop_column("finished_at")
        batch_op.drop_column("started_at")

    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("force_run_requested_at")
