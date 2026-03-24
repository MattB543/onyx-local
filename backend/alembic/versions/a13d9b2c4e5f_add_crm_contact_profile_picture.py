"""add crm contact profile picture column

Revision ID: a13d9b2c4e5f
Revises: fe6ed23b0d78
Create Date: 2026-03-23 16:40:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a13d9b2c4e5f"
down_revision = "fe6ed23b0d78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_contact",
        sa.Column("profile_picture_file_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crm_contact", "profile_picture_file_id")
