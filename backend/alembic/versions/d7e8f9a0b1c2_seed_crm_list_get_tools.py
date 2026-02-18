"""seed_crm_list_get_tools

Revision ID: d7e8f9a0b1c2
Revises: c4e5f6a7b8c9
Create Date: 2026-02-17 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d7e8f9a0b1c2"
down_revision = "c4e5f6a7b8c9"
branch_labels = None
depends_on = None


NEW_CRM_TOOLS = [
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

# Also update descriptions for existing CRM tools
UPDATED_CRM_TOOLS = [
    {
        "in_code_tool_id": "CrmSearchTool",
        "description": (
            "Search CRM records by text query. Use this to find contacts by name or email, "
            "organizations by name, interactions by title or summary, or tags by name. "
            "Always search before creating to avoid duplicates. "
            "For structured filtering without a text query, use crm_list instead."
        ),
    },
    {
        "in_code_tool_id": "CrmCreateTool",
        "description": (
            "Create a new CRM contact, organization, or tag. Always search first to avoid "
            "duplicates. When creating a contact, set organization_id to link them to an "
            "existing org, and include tag_ids to apply tags. New contacts default to 'lead' status."
        ),
    },
    {
        "in_code_tool_id": "CrmUpdateTool",
        "description": (
            "Update fields on an existing CRM contact or organization. Requires the entity's UUID. "
            "Only include fields you want to change — omitted fields are left unchanged. "
            "Use this to fix info, change status, reassign ownership, or link a contact to an org."
        ),
    },
    {
        "in_code_tool_id": "CrmLogInteractionTool",
        "description": (
            "Log a call, meeting, email, note, or event in the CRM. Link it to a contact_id "
            "and/or organization_id. Include attendees by email or name — the system will match "
            "them to existing contacts and team members. Always include a summary with key points."
        ),
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    # Seed new tools
    for tool in NEW_CRM_TOOLS:
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

    # Update descriptions on existing CRM tools
    for tool in UPDATED_CRM_TOOLS:
        conn.execute(
            sa.text(
                """
                UPDATE tool
                SET description = :description
                WHERE in_code_tool_id = :in_code_tool_id
                """
            ),
            tool,
        )


def downgrade() -> None:
    conn = op.get_bind()

    for tool in NEW_CRM_TOOLS:
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
            WHERE in_code_tool_id IN ('CrmListTool', 'CrmGetTool')
            """
        )
    )

    # Restore original descriptions
    original_descriptions = {
        "CrmSearchTool": "Search contacts, organizations, interactions, and tags in CRM records.",
        "CrmCreateTool": "Create CRM entities such as contacts, organizations, and tags.",
        "CrmUpdateTool": "Update existing CRM contacts and organizations.",
        "CrmLogInteractionTool": "Log CRM interactions and associated attendees.",
    }
    for in_code_tool_id, description in original_descriptions.items():
        conn.execute(
            sa.text(
                """
                UPDATE tool
                SET description = :description
                WHERE in_code_tool_id = :in_code_tool_id
                """
            ),
            {"in_code_tool_id": in_code_tool_id, "description": description},
        )
