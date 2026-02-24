"""encrypt oauth tokens and llm custom config

Revision ID: a1d4f89ce352
Revises: f5b6c7d8e9f0
Create Date: 2026-02-24 10:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a1d4f89ce352"
down_revision = "f5b6c7d8e9f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "oauth_account",
        "access_token",
        existing_type=sa.Text(),
        type_=sa.LargeBinary(),
        existing_nullable=False,
        postgresql_using="convert_to(access_token, 'UTF8')",
    )
    op.alter_column(
        "oauth_account",
        "refresh_token",
        existing_type=sa.Text(),
        type_=sa.LargeBinary(),
        existing_nullable=False,
        postgresql_using="convert_to(refresh_token, 'UTF8')",
    )
    op.alter_column(
        "llm_provider",
        "custom_config",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.LargeBinary(),
        existing_nullable=True,
        postgresql_using=(
            "CASE WHEN custom_config IS NULL THEN NULL "
            "ELSE convert_to(custom_config::text, 'UTF8') END"
        ),
    )


def downgrade() -> None:
    op.alter_column(
        "llm_provider",
        "custom_config",
        existing_type=sa.LargeBinary(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using=(
            "CASE WHEN custom_config IS NULL THEN NULL "
            "ELSE convert_from(custom_config, 'UTF8')::jsonb END"
        ),
    )
    op.alter_column(
        "oauth_account",
        "refresh_token",
        existing_type=sa.LargeBinary(),
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="convert_from(refresh_token, 'UTF8')",
    )
    op.alter_column(
        "oauth_account",
        "access_token",
        existing_type=sa.LargeBinary(),
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="convert_from(access_token, 'UTF8')",
    )
