"""alert approval columns

Revision ID: 0003_alert_approval
Revises: 0002_chat_persistence
Create Date: 2026-05-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_alert_approval"
down_revision: str | None = "0002_chat_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.add_column(
            sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("acknowledged_by", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("resolved_by", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("alerts") as batch_op:
        batch_op.drop_column("resolved_by")
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("acknowledged_by")
        batch_op.drop_column("acknowledged_at")
        batch_op.drop_column("requires_approval")
