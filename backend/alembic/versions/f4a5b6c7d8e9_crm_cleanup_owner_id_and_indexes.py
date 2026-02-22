"""crm cleanup: drop owner_id, add missing indexes, fix defaults

Delta migration that bridges the gap between the OLD prod schema
(from the 5 original incremental CRM migrations ending at e3f4a5b6c7d8)
and the NEW desired schema (from the squashed migration + model cleanup).

All operations are idempotent:
 - On PROD (old schema): applies the delta (drop column, add indexes, fix default).
 - On FRESH DB (squashed migration already created correct schema): no-op.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-02-19 22:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Drop the legacy owner_id column from crm_contact
    #    (exists on prod from old migrations; absent on fresh DB)
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE crm_contact DROP COLUMN IF EXISTS owner_id;
        """
    )

    # ------------------------------------------------------------------
    # 2. Add missing indexes
    #    (present on fresh DB from squashed migration; absent on prod)
    #    Using CREATE INDEX IF NOT EXISTS for idempotency.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crm_contact_organization_id
            ON crm_contact (organization_id);
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crm_contact_status
            ON crm_contact (status);
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crm_interaction_contact_id
            ON crm_interaction (contact_id);
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crm_interaction_organization_id
            ON crm_interaction (organization_id);
        """
    )

    # ------------------------------------------------------------------
    # 3. Add missing CHECK constraints (idempotently)
    #    The squashed migration creates these, but old prod may not have them.
    # ------------------------------------------------------------------

    # ck_crm_settings_singleton  -- ensures crm_settings.id = 1
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_crm_settings_singleton'
                  AND conrelid = 'crm_settings'::regclass
            ) THEN
                ALTER TABLE crm_settings
                    ADD CONSTRAINT ck_crm_settings_singleton CHECK (id = 1);
            END IF;
        END
        $$;
        """
    )

    # ck_crm_interaction_attendee_one_target  -- exactly one of user_id / contact_id
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_crm_interaction_attendee_one_target'
                  AND conrelid = 'crm_interaction_attendee'::regclass
            ) THEN
                ALTER TABLE crm_interaction_attendee
                    ADD CONSTRAINT ck_crm_interaction_attendee_one_target
                    CHECK (
                        (user_id IS NOT NULL AND contact_id IS NULL) OR
                        (user_id IS NULL AND contact_id IS NOT NULL)
                    );
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------
    # 4. Fix server_default on crm_settings.enabled
    #    Old migration had DEFAULT false; model declares DEFAULT true.
    #    ALTER COLUMN ... SET DEFAULT is idempotent (just overwrites).
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE crm_settings ALTER COLUMN enabled SET DEFAULT true;
        """
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Reverse the above.  Since this is a pre-launch cleanup migration
    # the downgrade is provided for completeness but is not expected to
    # be exercised in production.
    # ------------------------------------------------------------------

    # 4. Revert default on crm_settings.enabled back to false
    op.execute(
        """
        ALTER TABLE crm_settings ALTER COLUMN enabled SET DEFAULT false;
        """
    )

    # 3. Drop CHECK constraints (if they exist)
    op.execute(
        """
        ALTER TABLE crm_interaction_attendee
            DROP CONSTRAINT IF EXISTS ck_crm_interaction_attendee_one_target;
        """
    )

    op.execute(
        """
        ALTER TABLE crm_settings
            DROP CONSTRAINT IF EXISTS ck_crm_settings_singleton;
        """
    )

    # 2. Drop the indexes we added
    op.execute("DROP INDEX IF EXISTS ix_crm_contact_organization_id;")
    op.execute("DROP INDEX IF EXISTS ix_crm_contact_status;")
    op.execute("DROP INDEX IF EXISTS ix_crm_interaction_contact_id;")
    op.execute("DROP INDEX IF EXISTS ix_crm_interaction_organization_id;")

    # 1. Re-add the owner_id column (nullable UUID FK to user.id)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'crm_contact'
                  AND column_name = 'owner_id'
            ) THEN
                ALTER TABLE crm_contact
                    ADD COLUMN owner_id UUID;
                ALTER TABLE crm_contact
                    ADD CONSTRAINT fk_crm_contact_owner_id
                    FOREIGN KEY (owner_id) REFERENCES "user" (id)
                    ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )
