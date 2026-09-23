"""crm updated_at triggers and attendee user fk cascade

A contact's or organization's updated_at now advances on any directly related
change (own fields, tags, owners, interactions, attendees, org membership, FK
cascades), so updated_at means "last activity". Postgres triggers do this so
every writer (tools, REST, CSV import, email job, cascades) is covered.

Also fixes crm_interaction_attendee.user_id: ON DELETE SET NULL violated the
one-target CHECK, so deleting a user who was an attendee failed. It is now
ON DELETE CASCADE.

Revision ID: 39db7165c7ac
Revises: b3e1f7a2c9d4
Create Date: 2026-09-23 12:50:52.120973

"""

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "39db7165c7ac"
down_revision = "b3e1f7a2c9d4"
branch_labels = None
depends_on = None

ATTENDEE_TABLE = "crm_interaction_attendee"
ATTENDEE_USER_FK = "crm_interaction_attendee_user_id_fkey"
ATTENDEE_CONTACT_INDEX = "ix_crm_interaction_attendee_contact_interaction"

TIMESTAMPED_TABLES = ("crm_contact", "crm_organization", "crm_interaction")

# (link table, parent table, FK column pointing at the parent)
LINK_TABLES = (
    ("crm_contact__tag", "crm_contact", "contact_id"),
    ("crm_organization__tag", "crm_organization", "organization_id"),
    ("crm_contact_owner", "crm_contact", "contact_id"),
)

# (trigger name, table) for every trigger this migration creates.
TRIGGERS = (
    *((f"{table}_set_updated_at", table) for table in TIMESTAMPED_TABLES),
    *((f"{link_table}_touch_parent", link_table) for link_table, _, _ in LINK_TABLES),
    ("crm_interaction_touch_related_ins_del", "crm_interaction"),
    ("crm_interaction_touch_related_upd", "crm_interaction"),
    ("crm_interaction_attendee_touch_related", ATTENDEE_TABLE),
    ("crm_contact_touch_organization_ins_del", "crm_contact"),
    ("crm_contact_touch_organization_upd", "crm_contact"),
)

FUNCTIONS = (
    "crm_set_updated_at()",
    "crm_touch_link_parent()",
    "crm_interaction_touch_related()",
    "crm_interaction_attendee_touch_related()",
    "crm_contact_touch_organization()",
    "crm_touch_rows(regclass, uuid[])",
)


def _current_schema() -> str:
    schema = op.get_bind().execute(text("SELECT current_schema()")).scalar()
    if not isinstance(schema, str):
        raise ValueError("Current schema is not a string")
    return schema


def _replace_attendee_user_fk(schema: str, on_delete: str) -> None:
    # Look the FK up by column: older prod schemas may use a different name.
    existing_names = (
        op.get_bind()
        .execute(
            text(
                """
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                JOIN pg_attribute att
                    ON att.attrelid = con.conrelid AND att.attnum = ANY (con.conkey)
                WHERE con.contype = 'f'
                  AND nsp.nspname = :schema
                  AND rel.relname = :table
                  AND att.attname = 'user_id'
                """
            ),
            {"schema": schema, "table": ATTENDEE_TABLE},
        )
        .scalars()
        .all()
    )
    for name in existing_names:
        op.execute(f'ALTER TABLE "{schema}".{ATTENDEE_TABLE} DROP CONSTRAINT "{name}"')
    op.execute(
        f"""
        ALTER TABLE "{schema}".{ATTENDEE_TABLE}
            ADD CONSTRAINT {ATTENDEE_USER_FK}
            FOREIGN KEY (user_id) REFERENCES "{schema}"."user" (id)
            ON DELETE {on_delete}
        """
    )


def upgrade() -> None:
    s = _current_schema()

    # BEFORE UPDATE: only assigns NEW. Monotonic per row, even when a later
    # transaction (or a second change in the same transaction) writes the row;
    # now() is the transaction start time and could go backwards.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION "{s}".crm_set_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := GREATEST(
                clock_timestamp(), OLD.updated_at + interval '1 microsecond'
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Touch = no-op UPDATE, which fires crm_set_updated_at. IDs are
    # de-duplicated and touched in sorted order to reduce deadlocks. A row
    # deleted earlier in the same statement (cascade) matches 0 rows.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION "{s}".crm_touch_rows(target regclass, ids uuid[])
        RETURNS void AS $$
        DECLARE
            target_id uuid;
        BEGIN
            FOR target_id IN
                SELECT DISTINCT u FROM unnest(ids) AS u WHERE u IS NOT NULL ORDER BY u
            LOOP
                EXECUTE format(
                    'UPDATE %s SET updated_at = updated_at WHERE id = $1', target
                ) USING target_id;
            END LOOP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Link tables: TG_ARGV[0] = parent table, TG_ARGV[1] = FK column.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION "{s}".crm_touch_link_parent()
        RETURNS trigger AS $$
        DECLARE
            ids uuid[] := ARRAY[]::uuid[];
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                ids := ids || (to_jsonb(OLD) ->> TG_ARGV[1])::uuid;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                ids := ids || (to_jsonb(NEW) ->> TG_ARGV[1])::uuid;
            END IF;
            PERFORM "{s}".crm_touch_rows(
                format('%I.%I', TG_TABLE_SCHEMA, TG_ARGV[0])::regclass, ids
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Interactions: old/new primary contact, every contact attendee (so
    # attendee-only contacts see edits), and old/new organization.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION "{s}".crm_interaction_touch_related()
        RETURNS trigger AS $$
        DECLARE
            target_id uuid;
            contact_ids uuid[] := ARRAY[]::uuid[];
            organization_ids uuid[] := ARRAY[]::uuid[];
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                target_id := OLD.id;
                contact_ids := contact_ids || OLD.contact_id;
                organization_ids := organization_ids || OLD.organization_id;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                target_id := NEW.id;
                contact_ids := contact_ids || NEW.contact_id;
                organization_ids := organization_ids || NEW.organization_id;
            END IF;
            contact_ids := contact_ids || ARRAY(
                SELECT a.contact_id
                FROM "{s}".crm_interaction_attendee a
                WHERE a.interaction_id = target_id AND a.contact_id IS NOT NULL
            );
            PERFORM "{s}".crm_touch_rows('"{s}".crm_contact'::regclass, contact_ids);
            PERFORM "{s}".crm_touch_rows(
                '"{s}".crm_organization'::regclass, organization_ids
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Attendees: old/new attendee contact and the interaction itself. Uses OLD,
    # so cascade deletes (interaction or contact delete) still touch correctly.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION "{s}".crm_interaction_attendee_touch_related()
        RETURNS trigger AS $$
        DECLARE
            contact_ids uuid[] := ARRAY[]::uuid[];
            interaction_ids uuid[] := ARRAY[]::uuid[];
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                contact_ids := contact_ids || OLD.contact_id;
                interaction_ids := interaction_ids || OLD.interaction_id;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                contact_ids := contact_ids || NEW.contact_id;
                interaction_ids := interaction_ids || NEW.interaction_id;
            END IF;
            PERFORM "{s}".crm_touch_rows('"{s}".crm_contact'::regclass, contact_ids);
            PERFORM "{s}".crm_touch_rows(
                '"{s}".crm_interaction'::regclass, interaction_ids
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Contacts: joining or leaving an organization touches that organization.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION "{s}".crm_contact_touch_organization()
        RETURNS trigger AS $$
        DECLARE
            organization_ids uuid[] := ARRAY[]::uuid[];
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                organization_ids := organization_ids || OLD.organization_id;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                organization_ids := organization_ids || NEW.organization_id;
            END IF;
            PERFORM "{s}".crm_touch_rows(
                '"{s}".crm_organization'::regclass, organization_ids
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table in TIMESTAMPED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON "{s}".{table}
                FOR EACH ROW EXECUTE FUNCTION "{s}".crm_set_updated_at()
            """
        )

    for link_table, parent_table, fk_column in LINK_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {link_table}_touch_parent
                AFTER INSERT OR UPDATE OR DELETE ON "{s}".{link_table}
                FOR EACH ROW EXECUTE FUNCTION
                    "{s}".crm_touch_link_parent('{parent_table}', '{fk_column}')
            """
        )

    # A touch only changes updated_at. Skipping those UPDATEs keeps touches
    # from chaining past directly linked records (interaction -> contact).
    op.execute(
        f"""
        CREATE TRIGGER crm_interaction_touch_related_ins_del
            AFTER INSERT OR DELETE ON "{s}".crm_interaction
            FOR EACH ROW EXECUTE FUNCTION "{s}".crm_interaction_touch_related()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER crm_interaction_touch_related_upd
            AFTER UPDATE ON "{s}".crm_interaction
            FOR EACH ROW
            WHEN ((to_jsonb(OLD) - 'updated_at') IS DISTINCT FROM
                  (to_jsonb(NEW) - 'updated_at'))
            EXECUTE FUNCTION "{s}".crm_interaction_touch_related()
        """
    )

    op.execute(
        f"""
        CREATE TRIGGER crm_interaction_attendee_touch_related
            AFTER INSERT OR UPDATE OR DELETE ON "{s}".{ATTENDEE_TABLE}
            FOR EACH ROW EXECUTE FUNCTION
                "{s}".crm_interaction_attendee_touch_related()
        """
    )

    op.execute(
        f"""
        CREATE TRIGGER crm_contact_touch_organization_ins_del
            AFTER INSERT OR DELETE ON "{s}".crm_contact
            FOR EACH ROW EXECUTE FUNCTION "{s}".crm_contact_touch_organization()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER crm_contact_touch_organization_upd
            AFTER UPDATE OF organization_id ON "{s}".crm_contact
            FOR EACH ROW
            WHEN (OLD.organization_id IS DISTINCT FROM NEW.organization_id)
            EXECUTE FUNCTION "{s}".crm_contact_touch_organization()
        """
    )

    _replace_attendee_user_fk(s, "CASCADE")

    # Serves "interactions where this contact is an attendee" lookups and
    # contact-delete cascades. The existing index leads with interaction_id.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {ATTENDEE_CONTACT_INDEX}
            ON "{s}".{ATTENDEE_TABLE} (contact_id, interaction_id)
            WHERE contact_id IS NOT NULL
        """
    )


def downgrade() -> None:
    s = _current_schema()

    op.execute(f'DROP INDEX IF EXISTS "{s}".{ATTENDEE_CONTACT_INDEX}')
    _replace_attendee_user_fk(s, "SET NULL")

    for trigger, table in TRIGGERS:
        op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON "{s}".{table}')
    for function in FUNCTIONS:
        op.execute(f'DROP FUNCTION IF EXISTS "{s}".{function}')
