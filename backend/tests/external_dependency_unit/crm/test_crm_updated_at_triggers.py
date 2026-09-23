"""The CRM updated_at triggers (migration 39db7165c7ac).

A contact's or organization's updated_at advances on any directly related
change, touches never chain past directly linked records, and timestamps never
go backwards.
"""

import asyncio
import importlib.util
import io
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import UploadFile
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from onyx.db.crm import (
    add_tag_to_contact,
    add_tag_to_organization,
    remove_tag_from_contact,
    remove_tag_from_organization,
    update_contact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import CrmAttendeeRole
from onyx.db.models import (
    CrmContact,
    CrmContact__Tag,
    CrmContactOwner,
    CrmInteraction,
    CrmInteractionAttendee,
    CrmOrganization,
    CrmOrganization__Tag,
    CrmTag,
    User,
    User__UserGroup,
)
from onyx.server.features.crm.api import import_contacts_csv
from onyx.server.features.crm.csv_utils import CONTACT_IMPORT_HEADERS
from tests.external_dependency_unit.crm.conftest import (
    CRM_TRIGGERS,
    CrmRecords,
    db_clock,
    stamp,
)

MIGRATION_FILE = (
    Path(__file__).parents[3]
    / "alembic"
    / "versions"
    / "39db7165c7ac_crm_updated_at_triggers.py"
)


def test_tag_add_and_remove_bump_contact_and_organization(
    db_session: Session, crm: CrmRecords
) -> None:
    contact = crm.contact()
    org = crm.org()
    tag = crm.tag()
    control = crm.contact()
    control_before = stamp(db_session, CrmContact, control.id)

    cutoff = db_clock(db_session)
    add_tag_to_contact(db_session, contact_id=contact.id, tag_id=tag.id)
    add_tag_to_organization(db_session, organization_id=org.id, tag_id=tag.id)
    added_contact = stamp(db_session, CrmContact, contact.id)
    added_org = stamp(db_session, CrmOrganization, org.id)
    assert added_contact > cutoff
    assert added_org > cutoff

    remove_tag_from_contact(db_session, contact_id=contact.id, tag_id=tag.id)
    remove_tag_from_organization(db_session, organization_id=org.id, tag_id=tag.id)
    assert stamp(db_session, CrmContact, contact.id) > added_contact
    assert stamp(db_session, CrmOrganization, org.id) > added_org

    assert stamp(db_session, CrmContact, control.id) == control_before


def test_no_op_tag_changes_do_not_bump(db_session: Session, crm: CrmRecords) -> None:
    contact = crm.contact()
    tag = crm.tag()
    other_tag = crm.tag()
    add_tag_to_contact(db_session, contact_id=contact.id, tag_id=tag.id)
    before = stamp(db_session, CrmContact, contact.id)

    add_tag_to_contact(db_session, contact_id=contact.id, tag_id=tag.id)
    remove_tag_from_contact(db_session, contact_id=contact.id, tag_id=other_tag.id)

    assert stamp(db_session, CrmContact, contact.id) == before


def test_owner_change_bumps_contact(db_session: Session, crm: CrmRecords) -> None:
    contact = crm.contact()
    user = crm.user()

    cutoff = db_clock(db_session)
    update_contact(db_session, contact=contact, patches={"owner_ids": [user.id]})
    added = stamp(db_session, CrmContact, contact.id)
    assert added > cutoff

    update_contact(db_session, contact=contact, patches={"owner_ids": []})
    assert stamp(db_session, CrmContact, contact.id) > added


def test_link_row_update_bumps_old_and_new_parent(
    db_session: Session, crm: CrmRecords
) -> None:
    tag = crm.tag()
    user = crm.user()
    old_contact, new_contact = crm.contact(), crm.contact()
    old_org, new_org = crm.org(), crm.org()
    add_tag_to_contact(db_session, contact_id=old_contact.id, tag_id=tag.id)
    add_tag_to_organization(db_session, organization_id=old_org.id, tag_id=tag.id)
    db_session.add(CrmContactOwner(contact_id=old_contact.id, user_id=user.id))
    db_session.commit()

    for statement, model, old_id, new_id in (
        (
            update(CrmContact__Tag)
            .where(CrmContact__Tag.contact_id == old_contact.id)
            .values(contact_id=new_contact.id),
            CrmContact,
            old_contact.id,
            new_contact.id,
        ),
        (
            update(CrmContactOwner)
            .where(CrmContactOwner.contact_id == old_contact.id)
            .values(contact_id=new_contact.id),
            CrmContact,
            old_contact.id,
            new_contact.id,
        ),
        (
            update(CrmOrganization__Tag)
            .where(CrmOrganization__Tag.organization_id == old_org.id)
            .values(organization_id=new_org.id),
            CrmOrganization,
            old_org.id,
            new_org.id,
        ),
    ):
        cutoff = db_clock(db_session)
        db_session.execute(statement)
        db_session.commit()
        assert stamp(db_session, model, old_id) > cutoff
        assert stamp(db_session, model, new_id) > cutoff


def test_interaction_changes_bump_primary_attendee_and_org(
    db_session: Session, crm: CrmRecords
) -> None:
    primary = crm.contact()
    attendee_only = crm.contact()
    other_contact = crm.contact()
    org = crm.org()
    other_org = crm.org()

    cutoff = db_clock(db_session)
    interaction = crm.interaction(
        contact_id=primary.id,
        organization_id=org.id,
        attendee_contact_ids=[attendee_only.id],
    )
    for model, record_id in (
        (CrmContact, primary.id),
        (CrmContact, attendee_only.id),
        (CrmOrganization, org.id),
    ):
        assert stamp(db_session, model, record_id) > cutoff
    other_contact_before = stamp(db_session, CrmContact, other_contact.id)
    other_org_before = stamp(db_session, CrmOrganization, other_org.id)

    # A summary edit bumps the attendee-only contact too.
    cutoff = db_clock(db_session)
    interaction.summary = "Follow up next week."
    db_session.commit()
    for model, record_id in (
        (CrmContact, primary.id),
        (CrmContact, attendee_only.id),
        (CrmOrganization, org.id),
        (CrmInteraction, interaction.id),
    ):
        assert stamp(db_session, model, record_id) > cutoff
    assert stamp(db_session, CrmContact, other_contact.id) == other_contact_before
    assert stamp(db_session, CrmOrganization, other_org.id) == other_org_before

    # Re-linking bumps both the old and the new contact and org.
    cutoff = db_clock(db_session)
    interaction.contact_id = other_contact.id
    interaction.organization_id = other_org.id
    db_session.commit()
    for model, record_id in (
        (CrmContact, primary.id),
        (CrmContact, other_contact.id),
        (CrmOrganization, org.id),
        (CrmOrganization, other_org.id),
    ):
        assert stamp(db_session, model, record_id) > cutoff


def test_attendee_changes_bump_attendee_and_interaction_only(
    db_session: Session, crm: CrmRecords
) -> None:
    primary = crm.contact()
    org = crm.org()
    attendee = crm.contact()
    interaction = crm.interaction(contact_id=primary.id, organization_id=org.id)
    primary_before = stamp(db_session, CrmContact, primary.id)
    org_before = stamp(db_session, CrmOrganization, org.id)

    cutoff = db_clock(db_session)
    db_session.add(
        CrmInteractionAttendee(
            interaction_id=interaction.id,
            contact_id=attendee.id,
            role=CrmAttendeeRole.ATTENDEE,
        )
    )
    db_session.commit()
    assert stamp(db_session, CrmContact, attendee.id) > cutoff
    assert stamp(db_session, CrmInteraction, interaction.id) > cutoff

    other = crm.contact()
    for statement, touched_contact_ids in (
        (
            update(CrmInteractionAttendee)
            .where(CrmInteractionAttendee.contact_id == attendee.id)
            .values(role=CrmAttendeeRole.ORGANIZER),
            [attendee.id],
        ),
        (
            update(CrmInteractionAttendee)
            .where(CrmInteractionAttendee.contact_id == attendee.id)
            .values(contact_id=other.id),
            [attendee.id, other.id],
        ),
        (
            delete(CrmInteractionAttendee).where(
                CrmInteractionAttendee.contact_id == other.id
            ),
            [other.id],
        ),
    ):
        cutoff = db_clock(db_session)
        db_session.execute(statement)
        db_session.commit()
        assert stamp(db_session, CrmInteraction, interaction.id) > cutoff
        for contact_id in touched_contact_ids:
            assert stamp(db_session, CrmContact, contact_id) > cutoff

    # The interaction touch does not chain on to its primary contact or org.
    assert stamp(db_session, CrmContact, primary.id) == primary_before
    assert stamp(db_session, CrmOrganization, org.id) == org_before


def test_contact_insert_move_and_delete_bump_organizations(
    db_session: Session, crm: CrmRecords
) -> None:
    org = crm.org()
    other_org = crm.org()

    cutoff = db_clock(db_session)
    contact = crm.contact(organization_id=org.id)
    assert stamp(db_session, CrmOrganization, org.id) > cutoff

    # A contact field edit does not touch its organization.
    org_before = stamp(db_session, CrmOrganization, org.id)
    contact.title = "Director"
    db_session.commit()
    assert stamp(db_session, CrmOrganization, org.id) == org_before

    cutoff = db_clock(db_session)
    contact.organization_id = other_org.id
    db_session.commit()
    assert stamp(db_session, CrmOrganization, org.id) > cutoff
    assert stamp(db_session, CrmOrganization, other_org.id) > cutoff

    cutoff = db_clock(db_session)
    db_session.execute(delete(CrmContact).where(CrmContact.id == contact.id))
    db_session.commit()
    assert stamp(db_session, CrmOrganization, other_org.id) > cutoff


def test_user_delete_cascades_bump_linked_records(
    db_session: Session, crm: CrmRecords
) -> None:
    user = crm.user()
    owned = crm.contact()
    db_session.add(CrmContactOwner(contact_id=owned.id, user_id=user.id))
    db_session.commit()
    created = crm.contact(created_by=user.id)
    attended = crm.interaction(attendee_user_ids=[user.id])
    logged_primary = crm.contact()
    logged_org = crm.org()
    crm.interaction(
        logged_by=user.id,
        contact_id=logged_primary.id,
        organization_id=logged_org.id,
    )
    user_id = user.id

    cutoff = db_clock(db_session)
    db_session.execute(
        delete(User__UserGroup).where(User__UserGroup.user_id == user_id)
    )
    db_session.execute(delete(User).where(User.__table__.c.id == user_id))
    db_session.commit()

    remaining = db_session.scalar(
        select(func.count())
        .select_from(CrmInteractionAttendee)
        .where(CrmInteractionAttendee.user_id == user_id)
    )
    assert remaining == 0
    assert stamp(db_session, CrmContact, owned.id) > cutoff
    assert stamp(db_session, CrmContact, created.id) > cutoff
    assert stamp(db_session, CrmInteraction, attended.id) > cutoff
    assert stamp(db_session, CrmContact, logged_primary.id) > cutoff
    assert stamp(db_session, CrmOrganization, logged_org.id) > cutoff


def test_tag_delete_bumps_tagged_records(db_session: Session, crm: CrmRecords) -> None:
    contact = crm.contact()
    org = crm.org()
    tag = crm.tag()
    add_tag_to_contact(db_session, contact_id=contact.id, tag_id=tag.id)
    add_tag_to_organization(db_session, organization_id=org.id, tag_id=tag.id)

    cutoff = db_clock(db_session)
    db_session.execute(delete(CrmTag).where(CrmTag.id == tag.id))
    db_session.commit()

    assert stamp(db_session, CrmContact, contact.id) > cutoff
    assert stamp(db_session, CrmOrganization, org.id) > cutoff


def test_contact_delete_cascades_bump_linked_records(
    db_session: Session, crm: CrmRecords
) -> None:
    member_org = crm.org()
    interaction_org = crm.org()
    doomed = crm.contact(organization_id=member_org.id)
    other_primary = crm.contact()
    as_primary = crm.interaction(
        contact_id=doomed.id, organization_id=interaction_org.id
    )
    as_attendee = crm.interaction(
        contact_id=other_primary.id, attendee_contact_ids=[doomed.id]
    )
    other_primary_before = stamp(db_session, CrmContact, other_primary.id)

    cutoff = db_clock(db_session)
    db_session.execute(delete(CrmContact).where(CrmContact.id == doomed.id))
    db_session.commit()

    assert stamp(db_session, CrmOrganization, member_org.id) > cutoff
    assert stamp(db_session, CrmOrganization, interaction_org.id) > cutoff
    assert stamp(db_session, CrmInteraction, as_primary.id) > cutoff
    assert stamp(db_session, CrmInteraction, as_attendee.id) > cutoff
    assert stamp(db_session, CrmContact, other_primary.id) == other_primary_before


def test_interaction_delete_bumps_primary_attendees_and_org(
    db_session: Session, crm: CrmRecords
) -> None:
    primary = crm.contact()
    attendee = crm.contact()
    org = crm.org()
    interaction = crm.interaction(
        contact_id=primary.id,
        organization_id=org.id,
        attendee_contact_ids=[attendee.id],
    )

    cutoff = db_clock(db_session)
    db_session.execute(
        delete(CrmInteraction).where(CrmInteraction.id == interaction.id)
    )
    db_session.commit()

    assert stamp(db_session, CrmContact, primary.id) > cutoff
    assert stamp(db_session, CrmContact, attendee.id) > cutoff
    assert stamp(db_session, CrmOrganization, org.id) > cutoff


def test_organization_delete_bumps_members_and_interaction_contacts(
    db_session: Session, crm: CrmRecords
) -> None:
    org = crm.org()
    member = crm.contact(organization_id=org.id)
    primary = crm.contact()
    interaction = crm.interaction(contact_id=primary.id, organization_id=org.id)

    cutoff = db_clock(db_session)
    db_session.execute(delete(CrmOrganization).where(CrmOrganization.id == org.id))
    db_session.commit()

    assert stamp(db_session, CrmContact, member.id) > cutoff
    assert stamp(db_session, CrmContact, primary.id) > cutoff
    assert stamp(db_session, CrmInteraction, interaction.id) > cutoff


def test_concurrent_transactions_never_move_updated_at_backwards(
    db_session: Session, crm: CrmRecords
) -> None:
    contact = crm.contact()

    with (
        get_session_with_current_tenant() as early,
        get_session_with_current_tenant() as late,
    ):
        early_start = early.execute(text("SELECT now()")).scalar_one()

        late.execute(
            update(CrmContact).where(CrmContact.id == contact.id).values(notes="late")
        )
        late.commit()
        late_stamp = stamp(late, CrmContact, contact.id)
        # now() in the early transaction would have moved the stamp backwards.
        assert early_start < late_stamp

        early.execute(
            update(CrmContact).where(CrmContact.id == contact.id).values(notes="early")
        )
        early.commit()

    assert stamp(db_session, CrmContact, contact.id) > late_stamp


def _wait_until_blocked(db_session: Session, pid: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        wait_type = db_session.execute(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
            {"pid": pid},
        ).scalar()
        db_session.commit()
        if wait_type == "Lock":
            return
        time.sleep(0.05)
    raise AssertionError("The second writer never waited on a lock.")


def _run_blocked_writer(
    db_session: Session,
    holder: Session,
    writer: Session,
    write: Callable[[Session], Any],
    holder_write: Callable[[Session], Any] | None = None,
) -> None:
    """Run write(writer) in a thread until it waits on holder's row locks.
    Then run holder_write(holder), commit holder, and require the writer to
    finish without an error (a deadlock would fail one of them)."""
    errors: list[BaseException] = []
    writer.execute(text("SET LOCAL lock_timeout = '10s'"))
    writer_pid = writer.execute(text("SELECT pg_backend_pid()")).scalar_one()

    def target() -> None:
        try:
            write(writer)
            writer.commit()
        except BaseException as e:
            errors.append(e)

    thread = threading.Thread(target=target)
    thread.start()
    try:
        _wait_until_blocked(db_session, writer_pid)
        if holder_write is not None:
            holder_write(holder)
    finally:
        holder.commit()
        thread.join(timeout=15)
    assert not thread.is_alive()
    assert errors == []


def test_waiting_writer_stamps_after_the_committed_value(
    db_session: Session, crm: CrmRecords
) -> None:
    contact = crm.contact()

    with (
        get_session_with_current_tenant() as first,
        get_session_with_current_tenant() as second,
    ):
        first.execute(
            update(CrmContact).where(CrmContact.id == contact.id).values(notes="1")
        )
        first_stamp = stamp(first, CrmContact, contact.id)
        _run_blocked_writer(
            db_session,
            holder=first,
            writer=second,
            write=lambda session: session.execute(
                update(CrmContact).where(CrmContact.id == contact.id).values(notes="2")
            ),
        )

    assert stamp(db_session, CrmContact, contact.id) > first_stamp


def test_interaction_edit_and_attendee_change_do_not_deadlock(
    db_session: Session, crm: CrmRecords
) -> None:
    """Every trigger locks the interaction before its contacts. If the attendee
    trigger locked the contact first, the editor's touch of that contact
    would deadlock with the waiting attendee change."""
    attendee = crm.contact()
    interaction = crm.interaction(attendee_contact_ids=[attendee.id])

    with (
        get_session_with_current_tenant() as editor,
        get_session_with_current_tenant() as attendee_writer,
    ):
        editor.execute(text("SET LOCAL lock_timeout = '10s'"))
        # The row lock an ordinary UPDATE takes.
        editor.execute(
            select(CrmInteraction.id)
            .where(CrmInteraction.id == interaction.id)
            .with_for_update(key_share=True)
        )
        _run_blocked_writer(
            db_session,
            holder=editor,
            writer=attendee_writer,
            write=lambda session: session.execute(
                update(CrmInteractionAttendee)
                .where(CrmInteractionAttendee.contact_id == attendee.id)
                .values(role=CrmAttendeeRole.ORGANIZER)
            ),
            holder_write=lambda session: session.execute(
                update(CrmInteraction)
                .where(CrmInteraction.id == interaction.id)
                .values(summary="edited")
            ),
        )

    role = db_session.scalar(
        select(CrmInteractionAttendee.role).where(
            CrmInteractionAttendee.contact_id == attendee.id
        )
    )
    assert role == CrmAttendeeRole.ORGANIZER


def test_two_changes_in_one_transaction_get_increasing_stamps(
    db_session: Session, crm: CrmRecords
) -> None:
    contact = crm.contact()
    tag = crm.tag()

    contact.notes = "first"
    db_session.flush()
    first = stamp(db_session, CrmContact, contact.id)
    add_tag_to_contact(db_session, contact_id=contact.id, tag_id=tag.id, commit=False)
    db_session.flush()
    second = stamp(db_session, CrmContact, contact.id)
    db_session.commit()

    assert second > first


def test_stamp_never_goes_below_stored_value(
    db_session: Session, crm: CrmRecords
) -> None:
    future = datetime(2100, 1, 1, tzinfo=timezone.utc)
    contact = crm.contact(updated_at=future)

    contact.notes = "touched"
    db_session.commit()

    assert stamp(db_session, CrmContact, contact.id) == future + timedelta(
        microseconds=1
    )


def test_savepoint_rollback_leaves_stamp_unchanged(
    db_session: Session, crm: CrmRecords
) -> None:
    contact = crm.contact()
    tag = crm.tag()
    before = stamp(db_session, CrmContact, contact.id)

    savepoint = db_session.begin_nested()
    add_tag_to_contact(db_session, contact_id=contact.id, tag_id=tag.id, commit=False)
    db_session.flush()
    assert stamp(db_session, CrmContact, contact.id) > before
    savepoint.rollback()
    db_session.commit()

    assert stamp(db_session, CrmContact, contact.id) == before


def test_csv_dry_run_leaves_stamps_unchanged(
    db_session: Session, crm: CrmRecords
) -> None:
    org = crm.org()
    contact = crm.contact(last_name="Dryrun", organization_id=org.id)
    contact_before = stamp(db_session, CrmContact, contact.id)
    org_before = stamp(db_session, CrmOrganization, org.id)

    headers = ["id", *CONTACT_IMPORT_HEADERS]
    values: dict[str, str] = {
        "id": str(contact.id),
        "first_name": contact.first_name or "",
        "last_name": "Dryrun",
        "status": "lead",
        "notes": "changed by the dry run",
        "tags": f"dry-run-tag-{contact.id.hex[:8]}",
    }
    csv_text = ",".join(headers) + "\n" + ",".join(values.get(h, "") for h in headers)
    upload = UploadFile(file=io.BytesIO(csv_text.encode()), filename="contacts.csv")

    result = asyncio.run(
        import_contacts_csv(file=upload, dry_run=True, user=None, db_session=db_session)
    )

    assert result.errors == []
    assert result.updated == 1
    assert stamp(db_session, CrmContact, contact.id) == contact_before
    assert stamp(db_session, CrmOrganization, org.id) == org_before


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "crm_trigger_migration", MIGRATION_FILE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _trigger_names(db_session: Session) -> set[str]:
    return set(
        db_session.scalars(
            text(
                "SELECT t.tgname FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE NOT t.tgisinternal AND n.nspname = current_schema()"
            )
        )
    )


def _crm_functions(db_session: Session) -> set[str]:
    return set(
        db_session.scalars(
            text(
                "SELECT p.proname FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = current_schema() AND p.proname LIKE 'crm\\_%'"
            )
        )
    )


def _attendee_user_fks(db_session: Session) -> list[tuple[str, str]]:
    rows = db_session.execute(
        text(
            "SELECT con.conname, con.confdeltype FROM pg_constraint con "
            "JOIN pg_attribute att ON att.attrelid = con.conrelid "
            "AND att.attnum = ANY (con.conkey) "
            "WHERE con.contype = 'f' "
            "AND con.conrelid = 'crm_interaction_attendee'::regclass "
            "AND att.attname = 'user_id'"
        )
    )
    return [(row[0], row[1]) for row in rows]


def _attendee_contact_index(db_session: Session) -> str | None:
    return db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema() "
            "AND indexname = 'ix_crm_interaction_attendee_contact_interaction'"
        )
    ).scalar()


def test_migration_downgrade_and_upgrade_round_trip() -> None:
    """Runs downgrade() then upgrade() in one transaction and rolls it back.
    The FK is renamed in between, as older production schemas name it
    differently."""
    migration = _load_migration()
    with get_session_with_current_tenant() as session:
        connection = session.connection()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert _trigger_names(session).isdisjoint(CRM_TRIGGERS)
            assert _crm_functions(session) == set()
            assert _attendee_contact_index(session) is None
            assert _attendee_user_fks(session) == [
                ("crm_interaction_attendee_user_id_fkey", "n")
            ]

            session.execute(
                text(
                    "ALTER TABLE crm_interaction_attendee RENAME CONSTRAINT "
                    "crm_interaction_attendee_user_id_fkey TO legacy_attendee_user_fk"
                )
            )
            migration.upgrade()
            assert CRM_TRIGGERS <= _trigger_names(session)
            assert _crm_functions(session) == {
                "crm_set_updated_at",
                "crm_touch_rows",
                "crm_touch_link_parent",
                "crm_interaction_touch_related",
                "crm_interaction_attendee_touch_related",
                "crm_contact_touch_organization",
            }
            assert _attendee_user_fks(session) == [
                ("crm_interaction_attendee_user_id_fkey", "c")
            ]
            index_def = _attendee_contact_index(session)
            assert index_def is not None
            assert "(contact_id, interaction_id)" in index_def
            assert "WHERE (contact_id IS NOT NULL)" in index_def
        session.rollback()
