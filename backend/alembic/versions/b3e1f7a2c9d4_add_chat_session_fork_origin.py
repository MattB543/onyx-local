"""add chat session fork origin

Revision ID: b3e1f7a2c9d4
Revises: 1794c56fdb7c
Create Date: 2026-09-10 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b3e1f7a2c9d4"
down_revision = "1794c56fdb7c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bookmark to the session a chat was branched from. SET NULL so deleting
    # the original never blocks and the branch keeps working.
    op.add_column(
        "chat_session",
        sa.Column(
            "forked_from_chat_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "chat_session.id",
                name="chat_session_forked_from_chat_session_id_fkey",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("chat_session", "forked_from_chat_session_id")
