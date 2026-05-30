"""compat_placeholder_seed_crm_tools

Compatibility placeholder for the legacy CRM seed revision.

NOTE: this fork migration originally used revision id b6c7d8e9f0a1, which
collided with upstream's b6c7d8e9f0a1 (drop_persona_llm_override_strings,
PR #10855) introduced in the 2026-05-30 upstream sync. The fork copy was
renamed to b6c7d8e9f0a2 to resolve the collision; c4e5f6a7b8c9 (its only
child) was updated to point at the new id.

Revision ID: b6c7d8e9f0a2
Revises: a9f1c2d3e4f5
Create Date: 2026-02-22 16:40:00.000000
"""


# revision identifiers, used by Alembic.
revision = "b6c7d8e9f0a2"
down_revision = "a9f1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op compatibility placeholder.
    pass


def downgrade() -> None:
    # No-op compatibility placeholder.
    pass

