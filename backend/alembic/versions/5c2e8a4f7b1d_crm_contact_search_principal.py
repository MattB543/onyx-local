"""add principal to crm_contact full-text search

Contacts were not found by the name of the official they work for (their
principal). Postgres 16 cannot change a generated column's expression, so this
drops and re-adds crm_contact.search_tsv and its GIN index.

Revision ID: 5c2e8a4f7b1d
Revises: 39db7165c7ac
Create Date: 2026-09-23 18:30:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "5c2e8a4f7b1d"
down_revision = "39db7165c7ac"
branch_labels = None
depends_on = None

SEARCH_INDEX = "ix_crm_contact_search_tsv"

SEARCH_TSV_WITH_PRINCIPAL = """
    setweight(to_tsvector('english', coalesce(first_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(last_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(email, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(principal, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(title, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(notes, '')), 'D')
"""

SEARCH_TSV_ORIGINAL = """
    setweight(to_tsvector('english', coalesce(first_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(last_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(email, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(title, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(notes, '')), 'D')
"""


def _replace_search_tsv(expression: str) -> None:
    # A table rewrite fires no row triggers, so updated_at is not changed.
    op.execute(f"DROP INDEX IF EXISTS {SEARCH_INDEX}")
    op.execute("ALTER TABLE crm_contact DROP COLUMN IF EXISTS search_tsv")
    op.execute(
        "ALTER TABLE crm_contact ADD COLUMN search_tsv tsvector "
        f"GENERATED ALWAYS AS ({expression}) STORED"
    )
    op.execute(f"CREATE INDEX {SEARCH_INDEX} ON crm_contact USING GIN (search_tsv)")


def upgrade() -> None:
    _replace_search_tsv(SEARCH_TSV_WITH_PRINCIPAL)


def downgrade() -> None:
    _replace_search_tsv(SEARCH_TSV_ORIGINAL)
