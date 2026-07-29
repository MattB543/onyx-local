"""merge upstream sync batch6 heads

Revision ID: e4f7a2b91c08
Revises: c3b81de70f45, b7e9a3c1d2f4
Create Date: 2026-07-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4f7a2b91c08"
down_revision = ("c3b81de70f45", "b7e9a3c1d2f4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
