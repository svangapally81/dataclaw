"""align foreign key delete actions

Revision ID: 0018_fk_delete_actions
Revises: 0017_connector_sync_state
Create Date: 2026-05-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_fk_delete_actions"
down_revision: str | None = "0017_connector_sync_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FK_ACTIONS: tuple[tuple[str, tuple[str, ...], str, tuple[str, ...], str], ...] = (
    ("datasets", ("connector_id",), "connectors", ("id",), "CASCADE"),
    ("table_assets", ("dataset_id",), "datasets", ("id",), "CASCADE"),
    ("chat_threads", ("user_id",), "users", ("id",), "CASCADE"),
    ("agent_mcp_grants", ("agent_id",), "agents", ("id",), "CASCADE"),
    ("agent_write_audit", ("agent_id",), "agents", ("id",), "SET NULL"),
    ("agent_write_audit", ("alert_id",), "alerts", ("id",), "SET NULL"),
    ("knowledge_nodes", ("primary_wiki_page_id",), "wiki_pages", ("id",), "SET NULL"),
    ("knowledge_edges", ("src_node_id",), "knowledge_nodes", ("id",), "CASCADE"),
    ("knowledge_edges", ("dst_node_id",), "knowledge_nodes", ("id",), "CASCADE"),
    ("monitoring_configs", ("connector_id",), "connectors", ("id",), "CASCADE"),
    ("agents", ("target_connector_id",), "connectors", ("id",), "SET NULL"),
    ("agent_tool_call", ("run_id",), "agent_runs", ("id",), "CASCADE"),
    ("column_lineage_edges", ("source_page_id",), "wiki_pages", ("id",), "SET NULL"),
)


def _constraint_name(table: str, constrained_columns: tuple[str, ...], referred_table: str) -> tuple[str | None, str | None]:
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if tuple(fk["constrained_columns"]) != constrained_columns:
            continue
        if fk["referred_table"] != referred_table:
            continue
        return fk.get("name"), (fk.get("options") or {}).get("ondelete")
    return None, None


def _apply(ondelete: str) -> None:
    for table, columns, referred_table, referred_columns, desired_ondelete in FK_ACTIONS:
        if desired_ondelete != ondelete:
            continue
        current_name, current_ondelete = _constraint_name(table, columns, referred_table)
        if current_ondelete and current_ondelete.upper() == desired_ondelete:
            continue
        if not current_name:
            continue
        constraint_name = f"fk_{table}_{'_'.join(columns)}_{referred_table}"
        op.drop_constraint(current_name, table, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table,
            referred_table,
            list(columns),
            list(referred_columns),
            ondelete=desired_ondelete,
        )


def upgrade() -> None:
    _apply("CASCADE")
    _apply("SET NULL")


def downgrade() -> None:
    for table, columns, referred_table, referred_columns, _desired_ondelete in FK_ACTIONS:
        current_name, current_ondelete = _constraint_name(table, columns, referred_table)
        if not current_name or not current_ondelete:
            continue
        constraint_name = f"fk_{table}_{'_'.join(columns)}_{referred_table}"
        op.drop_constraint(current_name, table, type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            table,
            referred_table,
            list(columns),
            list(referred_columns),
        )
