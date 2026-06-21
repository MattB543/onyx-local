"""make crm_contact first_name nullable

Revision ID: a7c1e9d4b2f3
Revises: def916608374
Create Date: 2026-06-13 00:00:00.000000

`down_revision` is the prior single head as reported by `alembic heads`
(def916608374, "merge_upstream_sync_20260530_heads"). After this revision,
`alembic heads` again reports a single head (a7c1e9d4b2f3).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7c1e9d4b2f3"
down_revision = "def916608374"
branch_labels = None
depends_on = None


CONTACT_HAS_NAME_CONSTRAINT = "ck_crm_contact_has_name"


def upgrade() -> None:
    op.alter_column(
        "crm_contact",
        "first_name",
        existing_type=sa.String(),
        nullable=True,
    )
    # Normalize blank-string names to NULL so the "at least one name" invariant
    # is checked against real absence (consistent with how the app writes names).
    op.execute(
        "UPDATE crm_contact "
        "SET first_name = NULLIF(btrim(first_name), ''), "
        "    last_name = NULLIF(btrim(last_name), '')"
    )
    # Enforce the invariant at the database level as well as in the app: a
    # contact must always have at least a first or last name. If any existing
    # row would violate this (e.g. a blank first name with no last name), the
    # constraint creation fails loudly rather than leaving nameless rows.
    op.create_check_constraint(
        CONTACT_HAS_NAME_CONSTRAINT,
        "crm_contact",
        "first_name IS NOT NULL OR last_name IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        CONTACT_HAS_NAME_CONSTRAINT, "crm_contact", type_="check"
    )
    # The reverted application requires a non-null first_name. Refuse to
    # downgrade if any last-name-only contacts exist rather than silently
    # destroying data by backfilling a placeholder first name.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM crm_contact WHERE first_name IS NULL) THEN "
        "RAISE EXCEPTION 'Cannot downgrade: crm_contact rows with a NULL "
        "first_name exist; resolve them before re-imposing NOT NULL'; "
        "END IF; END $$;"
    )
    op.alter_column(
        "crm_contact",
        "first_name",
        existing_type=sa.String(),
        nullable=False,
    )
