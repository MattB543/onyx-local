"""add_crm_core_schema

Squashed migration: replaces the five incremental CRM migrations
(a9f1c2d3e4f5, b6c7d8e9f0a1, c4e5f6a7b8c9, d7e8f9a0b1c2, e3f4a5b6c7d8)
into a single migration that creates the full CRM schema and seeds all
CRM tools.

Revision ID: e3f4a5b6c7d8
Revises: e2f3a4b5c6d7
Create Date: 2026-02-19 21:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e3f4a5b6c7d8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# CRM tools – union of the two seed migrations
# ---------------------------------------------------------------------------

ALL_CRM_TOOLS = [
    {
        "name": "crm_search",
        "display_name": "CRM Search",
        "description": (
            "Search CRM records by text query. Use this to find contacts by name or email, "
            "organizations by name, interactions by title or summary, or tags by name. "
            "Always search before creating to avoid duplicates. "
            "For structured filtering without a text query, use crm_list instead."
        ),
        "in_code_tool_id": "CrmSearchTool",
        "enabled": True,
    },
    {
        "name": "crm_create",
        "display_name": "CRM Create",
        "description": (
            "Create a new CRM contact, organization, or tag. Always search first to avoid "
            "duplicates. When creating a contact, set organization_id to link them to an "
            "existing org, and include tag_ids to apply tags. New contacts default to 'lead' status."
        ),
        "in_code_tool_id": "CrmCreateTool",
        "enabled": True,
    },
    {
        "name": "crm_update",
        "display_name": "CRM Update",
        "description": (
            "Update fields on an existing CRM contact or organization. Requires the entity's UUID. "
            "Only include fields you want to change — omitted fields are left unchanged. "
            "Use this to fix info, change status, reassign ownership, or link a contact to an org."
        ),
        "in_code_tool_id": "CrmUpdateTool",
        "enabled": True,
    },
    {
        "name": "crm_log_interaction",
        "display_name": "CRM Log Interaction",
        "description": (
            "Log a call, meeting, email, note, or event in the CRM. Link it to a contact_id "
            "and/or organization_id. Include attendees by email or name — the system will match "
            "them to existing contacts and team members. Always include a summary with key points."
        ),
        "in_code_tool_id": "CrmLogInteractionTool",
        "enabled": True,
    },
    {
        "name": "crm_list",
        "display_name": "CRM List",
        "description": (
            "List and filter CRM records without a text query. Use this to browse contacts by "
            "status, list contacts at a specific organization, list recent interactions, or list "
            "all tags. For text-based searching, use crm_search instead."
        ),
        "in_code_tool_id": "CrmListTool",
        "enabled": True,
    },
    {
        "name": "crm_get",
        "display_name": "CRM Get",
        "description": (
            "Fetch full details of a specific CRM entity by UUID. Use after finding an entity "
            "via crm_search or crm_list. Optionally include related data like tags, interactions, "
            "organization, attendees, or contacts."
        ),
        "in_code_tool_id": "CrmGetTool",
        "enabled": True,
    },
]


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ── crm_settings ──────────────────────────────────────────────────────
    op.create_table(
        "crm_settings",
        sa.Column("id", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "tier2_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "tier3_deals", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "tier3_custom_fields",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "contact_stage_options",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text(
                "ARRAY['lead','active','inactive','archived']::varchar[]"
            ),
        ),
        sa.Column(
            "contact_category_suggestions",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text(
                "ARRAY['Policy Maker','Journalist','Academic','Allied Org','Lab Member']::varchar[]"
            ),
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

    # ── crm_organization ──────────────────────────────────────────────────
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

    # ── crm_contact (NO owner_id column) ──────────────────────────────────
    op.create_table(
        "crm_contact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(), nullable=False),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── crm_contact_owner (junction table, sole source of ownership) ──────
    op.create_table(
        "crm_contact_owner",
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["crm_contact.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("contact_id", "user_id"),
    )

    # ── crm_interaction (includes updated_at from the start) ──────────────
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["crm_contact.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["crm_organization.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["logged_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── crm_interaction_attendee ──────────────────────────────────────────
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
        sa.ForeignKeyConstraint(
            ["contact_id"], ["crm_contact.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND contact_id IS NULL) OR "
            "(user_id IS NULL AND contact_id IS NOT NULL)",
            name="ck_crm_interaction_attendee_one_target",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── crm_tag ───────────────────────────────────────────────────────────
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

    # ── crm_contact__tag ──────────────────────────────────────────────────
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
        sa.ForeignKeyConstraint(
            ["contact_id"], ["crm_contact.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["crm_tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("contact_id", "tag_id"),
    )

    # ── crm_organization__tag ─────────────────────────────────────────────
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

    # ── Indexes ───────────────────────────────────────────────────────────

    # Unique lower-case indexes
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

    # Interaction attendee indexes
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

    # Contact owner index
    op.create_index(
        "ix_crm_contact_owner_user_id",
        "crm_contact_owner",
        ["user_id"],
        unique=False,
    )

    # Contact lookup indexes (from the model)
    op.create_index(
        "ix_crm_contact_organization_id",
        "crm_contact",
        ["organization_id"],
    )
    op.create_index(
        "ix_crm_contact_status",
        "crm_contact",
        ["status"],
    )

    # Interaction lookup indexes (from the model)
    op.create_index(
        "ix_crm_interaction_contact_id",
        "crm_interaction",
        ["contact_id"],
    )
    op.create_index(
        "ix_crm_interaction_organization_id",
        "crm_interaction",
        ["organization_id"],
    )

    # ── Generated tsvector columns + GIN indexes ─────────────────────────
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

    # ── Seed CRM tools ────────────────────────────────────────────────────
    conn = op.get_bind()

    for tool in ALL_CRM_TOOLS:
        existing = conn.execute(
            sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
            {"in_code_tool_id": tool["in_code_tool_id"]},
        ).fetchone()

        if existing:
            tool_id = existing[0]
            conn.execute(
                sa.text(
                    """
                    UPDATE tool
                    SET name = :name,
                        display_name = :display_name,
                        description = :description,
                        enabled = :enabled
                    WHERE id = :tool_id
                    """
                ),
                {
                    **tool,
                    "tool_id": tool_id,
                },
            )
        else:
            tool_id = conn.execute(
                sa.text(
                    """
                    INSERT INTO tool (name, display_name, description, in_code_tool_id, enabled)
                    VALUES (:name, :display_name, :description, :in_code_tool_id, :enabled)
                    RETURNING id
                    """
                ),
                tool,
            ).scalar_one()

        conn.execute(
            sa.text(
                """
                INSERT INTO persona__tool (persona_id, tool_id)
                VALUES (0, :tool_id)
                ON CONFLICT DO NOTHING
                """
            ),
            {"tool_id": tool_id},
        )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Remove CRM tools
    conn = op.get_bind()

    for tool in ALL_CRM_TOOLS:
        conn.execute(
            sa.text(
                """
                DELETE FROM persona__tool
                WHERE tool_id IN (
                    SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id
                )
                """
            ),
            {"in_code_tool_id": tool["in_code_tool_id"]},
        )

    conn.execute(
        sa.text(
            """
            DELETE FROM tool
            WHERE in_code_tool_id IN (
                'CrmSearchTool',
                'CrmCreateTool',
                'CrmUpdateTool',
                'CrmLogInteractionTool',
                'CrmListTool',
                'CrmGetTool'
            )
            """
        )
    )

    # Drop tables in reverse dependency order
    op.drop_table("crm_organization__tag")
    op.drop_table("crm_contact__tag")
    op.drop_table("crm_tag")
    op.drop_table("crm_interaction_attendee")
    op.drop_table("crm_interaction")
    op.drop_table("crm_contact_owner")
    op.drop_table("crm_contact")
    op.drop_table("crm_organization")
    op.drop_table("crm_settings")
