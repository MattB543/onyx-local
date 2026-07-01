"""add crm contact policy fields

Revision ID: d4061bb581a7
Revises: d2a5f5e96234
Create Date: 2026-07-01 16:44:54.338787

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4061bb581a7"
down_revision = "d2a5f5e96234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_contact",
        sa.Column("party_affiliation", sa.String(), nullable=True),
    )
    op.add_column(
        "crm_contact",
        sa.Column("us_state", sa.String(), nullable=True),
    )
    op.add_column(
        "crm_contact",
        sa.Column("principal", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("crm_contact", "principal")
    op.drop_column("crm_contact", "us_state")
    op.drop_column("crm_contact", "party_affiliation")
