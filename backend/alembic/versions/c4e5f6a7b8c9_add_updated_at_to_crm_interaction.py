"""add_updated_at_to_crm_interaction

Revision ID: c4e5f6a7b8c9
Revises: b6c7d8e9f0a1
Create Date: 2026-02-16 18:05:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4e5f6a7b8c9"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_interaction",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("crm_interaction", "updated_at")
