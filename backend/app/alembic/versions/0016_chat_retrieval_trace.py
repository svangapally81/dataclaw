"""chat retrieval trace

Revision ID: 0016_chat_retrieval_trace
Revises: 0015_column_lineage_edges
Create Date: 2026-05-11
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_chat_retrieval_trace"
down_revision = "0015_column_lineage_edges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(sa.Column("retrieval_trace", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_column("retrieval_trace")
