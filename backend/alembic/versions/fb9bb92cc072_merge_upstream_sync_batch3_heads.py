"""merge upstream sync batch3 heads

Revision ID: fb9bb92cc072
Revises: f75baf85603b, 2e0b2b146de1
Create Date: 2026-07-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "fb9bb92cc072"
down_revision = ("f75baf85603b", "2e0b2b146de1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
