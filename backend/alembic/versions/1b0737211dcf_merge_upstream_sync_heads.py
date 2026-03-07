"""merge_upstream_sync_heads

Revision ID: 1b0737211dcf
Revises: a1d4f89ce352, a3b8d9e2f1c4
Create Date: 2026-03-07 12:52:23.146175

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1b0737211dcf"
down_revision = ("a1d4f89ce352", "a3b8d9e2f1c4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
