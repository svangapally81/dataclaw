"""chat chart spec

Revision ID: 0007_chat_chart_spec
Revises: 0006_agents_and_grants
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_chat_chart_spec"
down_revision: str | None = "0006_agents_and_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("chart_spec", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "chart_spec")
