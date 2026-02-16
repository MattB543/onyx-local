"""seed_crm_tools

Revision ID: b6c7d8e9f0a1
Revises: a9f1c2d3e4f5
Create Date: 2026-02-16 15:06:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b6c7d8e9f0a1"
down_revision = "a9f1c2d3e4f5"
branch_labels = None
depends_on = None


CRM_TOOLS = [
    {
        "name": "crm_search",
        "display_name": "CRM Search",
        "description": "Search contacts, organizations, interactions, and tags in CRM records.",
        "in_code_tool_id": "CrmSearchTool",
        "enabled": True,
    },
    {
        "name": "crm_create",
        "display_name": "CRM Create",
        "description": "Create CRM entities such as contacts, organizations, and tags.",
        "in_code_tool_id": "CrmCreateTool",
        "enabled": True,
    },
    {
        "name": "crm_update",
        "display_name": "CRM Update",
        "description": "Update existing CRM contacts and organizations.",
        "in_code_tool_id": "CrmUpdateTool",
        "enabled": True,
    },
    {
        "name": "crm_log_interaction",
        "display_name": "CRM Log Interaction",
        "description": "Log CRM interactions and associated attendees.",
        "in_code_tool_id": "CrmLogInteractionTool",
        "enabled": True,
    },
]


def upgrade() -> None:
    conn = op.get_bind()

    for tool in CRM_TOOLS:
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


def downgrade() -> None:
    conn = op.get_bind()

    for tool in CRM_TOOLS:
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
                'CrmLogInteractionTool'
            )
            """
        )
    )
