"""seed_search_calendar_tool

Ensure SearchCalendarTool exists and is linked to the default assistant.
This backfills environments that reached later heads without running the
original calendar-tool seed migration.

Revision ID: f5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-02-20 22:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


TOOL = {
    "name": "search_calendar",
    "display_name": "Calendar Search",
    "description": (
        "Search indexed Google Calendar events by date range, people, calendar, "
        "status, or text. Use this for scheduling questions such as upcoming meetings "
        "or what meetings happen tomorrow."
    ),
    "in_code_tool_id": "SearchCalendarTool",
    "enabled": True,
}


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text("SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id"),
        {"in_code_tool_id": TOOL["in_code_tool_id"]},
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
                **TOOL,
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
            TOOL,
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

    conn.execute(
        sa.text(
            """
            DELETE FROM persona__tool
            WHERE tool_id IN (
                SELECT id FROM tool WHERE in_code_tool_id = :in_code_tool_id
            )
            """
        ),
        {"in_code_tool_id": TOOL["in_code_tool_id"]},
    )

    conn.execute(
        sa.text(
            """
            DELETE FROM tool
            WHERE in_code_tool_id = :in_code_tool_id
            """
        ),
        {"in_code_tool_id": TOOL["in_code_tool_id"]},
    )
