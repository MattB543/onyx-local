"""merge_upstream_sync_heads

Revision ID: ebf99a6ad57e
Revises: 3debc2b55899, 563e4c5f4903
Create Date: 2026-08-03 13:52:10.692584

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "ebf99a6ad57e"
down_revision = ("3debc2b55899", "563e4c5f4903")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
