"""add_crm_core_schema

Revision ID: a9f1c2d3e4f5
Revises: 19c0ccb01687
Create Date: 2026-02-16 15:05:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a9f1c2d3e4f5"
down_revision = "19c0ccb01687"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_settings",
        sa.Column("id", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "tier2_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("tier3_deals", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "tier3_custom_fields",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.CheckConstraint("id = 1", name="ck_crm_settings_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crm_organization",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("website", sa.String(), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("size", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crm_contact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("linkedin_url", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["crm_organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crm_interaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("logged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["crm_contact.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["crm_organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["logged_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crm_interaction_attendee",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("interaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["crm_interaction.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["crm_contact.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND contact_id IS NULL) OR (user_id IS NULL AND contact_id IS NOT NULL)",
            name="ck_crm_interaction_attendee_one_target",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crm_tag",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "crm_contact__tag",
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["contact_id"], ["crm_contact.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["crm_tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("contact_id", "tag_id"),
    )

    op.create_table(
        "crm_organization__tag",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["crm_organization.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["crm_tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "tag_id"),
    )

    op.create_index(
        "ix_crm_organization_name_lower",
        "crm_organization",
        [sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "ix_crm_contact_email_lower",
        "crm_contact",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
    )
    op.create_index(
        "ix_crm_tag_name_lower",
        "crm_tag",
        [sa.text("lower(name)")],
        unique=True,
    )

    op.create_index(
        "ix_crm_interaction_attendee_interaction_id",
        "crm_interaction_attendee",
        ["interaction_id"],
    )
    op.create_index(
        "uq_crm_interaction_attendee_user",
        "crm_interaction_attendee",
        ["interaction_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_crm_interaction_attendee_contact",
        "crm_interaction_attendee",
        ["interaction_id", "contact_id"],
        unique=True,
        postgresql_where=sa.text("contact_id IS NOT NULL"),
    )

    op.execute(
        """
        ALTER TABLE crm_contact
        ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(first_name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(last_name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(email, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(title, '')), 'C') ||
            setweight(to_tsvector('english', coalesce(notes, '')), 'D')
        ) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE crm_organization
        ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(website, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(sector, '')), 'C') ||
            setweight(to_tsvector('english', coalesce(notes, '')), 'D')
        ) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE crm_interaction
        ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(summary, '')), 'B')
        ) STORED
        """
    )

    op.execute(
        "CREATE INDEX ix_crm_contact_search_tsv ON crm_contact USING GIN (search_tsv)"
    )
    op.execute(
        "CREATE INDEX ix_crm_organization_search_tsv ON crm_organization USING GIN (search_tsv)"
    )
    op.execute(
        "CREATE INDEX ix_crm_interaction_search_tsv ON crm_interaction USING GIN (search_tsv)"
    )


def downgrade() -> None:
    op.drop_table("crm_organization__tag")
    op.drop_table("crm_contact__tag")
    op.drop_table("crm_tag")
    op.drop_table("crm_interaction_attendee")
    op.drop_table("crm_interaction")
    op.drop_table("crm_contact")
    op.drop_table("crm_organization")
    op.drop_table("crm_settings")
