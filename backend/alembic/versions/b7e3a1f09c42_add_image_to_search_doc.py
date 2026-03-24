"""Add image column to search_doc table

Revision ID: b7e3a1f09c42
Revises: a13d9b2c4e5f
Create Date: 2026-03-24

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b7e3a1f09c42"
down_revision = "a13d9b2c4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("search_doc", sa.Column("image", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("search_doc", "image")
