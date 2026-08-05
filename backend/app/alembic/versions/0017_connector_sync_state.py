"""connector sync state

Revision ID: 0017_connector_sync_state
Revises: 0016_chat_retrieval_trace
Create Date: 2026-05-12
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_connector_sync_state"
down_revision = "0016_chat_retrieval_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("connectors") as batch_op:
        batch_op.add_column(sa.Column("sync_state", sa.String(length=40), nullable=False, server_default="never_synced"))
        batch_op.add_column(sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_sync_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("connectors") as batch_op:
        batch_op.drop_column("last_sync_error")
        batch_op.drop_column("last_synced_at")
        batch_op.drop_column("sync_state")
