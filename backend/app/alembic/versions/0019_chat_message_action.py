"""add chat message action

Revision ID: 0019_chat_message_action
Revises: 0018_fk_delete_actions
Create Date: 2026-05-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_chat_message_action"
down_revision: str | None = "0018_fk_delete_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("action", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "action")
