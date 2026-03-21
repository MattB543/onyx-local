"""merge_upstream_sync_heads

Revision ID: fe6ed23b0d78
Revises: 1b0737211dcf, 689433b0d8de
Create Date: 2026-03-21 17:12:09.904251

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fe6ed23b0d78"
down_revision = ("1b0737211dcf", "689433b0d8de")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
