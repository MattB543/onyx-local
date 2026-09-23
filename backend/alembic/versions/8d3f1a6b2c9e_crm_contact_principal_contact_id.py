"""link a crm contact's principal to the official's own contact

A staffer's principal was free text only. principal_contact_id links it to
the official's contact record. Existing rows stay unlinked; the text keeps
working as before.

Revision ID: 8d3f1a6b2c9e
Revises: 5c2e8a4f7b1d
Create Date: 2026-09-23 21:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "8d3f1a6b2c9e"
down_revision = "5c2e8a4f7b1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crm_contact",
        sa.Column("principal_contact_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "crm_contact_principal_contact_id_fkey",
        "crm_contact",
        "crm_contact",
        ["principal_contact_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_crm_contact_principal_not_self",
        "crm_contact",
        "principal_contact_id <> id",
    )
    op.create_index(
        "ix_crm_contact_principal_contact_id",
        "crm_contact",
        ["principal_contact_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_contact_principal_contact_id", table_name="crm_contact")
    op.drop_constraint(
        "ck_crm_contact_principal_not_self", "crm_contact", type_="check"
    )
    op.drop_constraint(
        "crm_contact_principal_contact_id_fkey", "crm_contact", type_="foreignkey"
    )
    op.drop_column("crm_contact", "principal_contact_id")
