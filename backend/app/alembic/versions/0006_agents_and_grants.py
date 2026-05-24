"""agents and mcp grants

Revision ID: 0006_agents_and_grants
Revises: 0005_logs_and_chat_archive
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_agents_and_grants"
down_revision: str | None = "0005_logs_and_chat_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("icon_key", sa.String(80), nullable=False, server_default="bot"),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("workspace_id", "name", name="uq_agents_workspace_name"),
    )
    op.create_index("ix_agents_workspace_id", "agents", ["workspace_id"])
    op.create_index("ix_agents_name", "agents", ["name"])
    op.create_table(
        "agent_mcp_grants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.String(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_slug", sa.String(80), nullable=False),
        sa.Column("read_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("write_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("agent_id", "connector_slug", name="uq_agent_grant_slug"),
    )
    op.create_index("ix_agent_mcp_grants_agent_id", "agent_mcp_grants", ["agent_id"])
    op.create_index("ix_agent_mcp_grants_connector_slug", "agent_mcp_grants", ["connector_slug"])


def downgrade() -> None:
    op.drop_index("ix_agent_mcp_grants_connector_slug", table_name="agent_mcp_grants")
    op.drop_index("ix_agent_mcp_grants_agent_id", table_name="agent_mcp_grants")
    op.drop_table("agent_mcp_grants")
    op.drop_index("ix_agents_name", table_name="agents")
    op.drop_index("ix_agents_workspace_id", table_name="agents")
    op.drop_table("agents")
