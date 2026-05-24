"""logs table and chat thread archive flag

Revision ID: 0005_logs_and_chat_archive
Revises: 0004_app_settings
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_logs_and_chat_archive"
down_revision: str | None = "0004_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_threads",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "chat_threads",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_threads_archived", "chat_threads", ["archived"])

    op.create_table(
        "log_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("logger_name", sa.String(120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("exception", sa.Text(), nullable=True),
    )
    op.create_index("ix_log_entries_timestamp", "log_entries", ["timestamp"])
    op.create_index("ix_log_entries_level", "log_entries", ["level"])
    op.create_index("ix_log_entries_logger_name", "log_entries", ["logger_name"])


def downgrade() -> None:
    op.drop_index("ix_log_entries_logger_name", table_name="log_entries")
    op.drop_index("ix_log_entries_level", table_name="log_entries")
    op.drop_index("ix_log_entries_timestamp", table_name="log_entries")
    op.drop_table("log_entries")
    op.drop_index("ix_chat_threads_archived", table_name="chat_threads")
    op.drop_column("chat_threads", "archived_at")
    op.drop_column("chat_threads", "archived")
