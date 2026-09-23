"""Offices (all contacts of one principal): the per-organization office list,
office-wide interactions, and the link from a staffer's principal to the
official's own contact (principal_contact_id)."""

import json
from queue import Queue
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.crm import (
    create_contact,
    delete_contact,
    list_contact_principals,
    list_contacts,
    list_interactions,
    update_contact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import CrmContact
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.crm.crm_get_tool import CrmGetTool
from onyx.tools.tool_implementations.crm.crm_list_tool import CrmListTool
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool
from tests.external_dependency_unit.crm.conftest import CrmRecords, stamp
from tests.external_dependency_unit.crm.test_crm_updated_at_triggers import (
    _run_blocked_writer,
)

PLACEMENT = Placement(turn_index=0, tab_index=0)


def call(tool: Any, **kwargs: Any) -> dict[str, Any]:
    return json.loads(tool.run(placement=PLACEMENT, **kwargs).rich_response)


def call_error(tool: Any, **kwargs: Any) -> str:
    with pytest.raises(ToolCallException) as exc_info:
        tool.run(placement=PLACEMENT, **kwargs)
    return exc_info.value.llm_facing_message


def unique_surname() -> str:
    # Keeps other rows in the shared test DB out of the results.
    return f"Jacobs{uuid4().hex[:8]}"


def test_org_principals_count_only_that_org(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    org = crm.org()
    crm.contact(organization_id=org.id, principal=f"Sara {surname}")
    crm.contact(organization_id=org.id, principal=f" sara {surname.lower()}")
    crm.contact(organization_id=org.id, principal=f"Todd {surname}")
    crm.contact(organization_id=org.id)
    crm.contact(organization_id=crm.org().id, principal=f"Sara {surname}")

    counts = {
        row.name.lower(): row.contact_count
        for row in list_contact_principals(db_session, organization_id=org.id)
    }
    assert counts == {f"sara {surname}".lower(): 2, f"todd {surname}".lower(): 1}


def test_office_interactions_cover_staff_and_linked_official(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    official = crm.contact(first_name="Sara", last_name=surname)
    linked = crm.contact(principal=f"Sara {surname}", principal_contact_id=official.id)
    unlinked = crm.contact(principal=f" sara {surname.lower()} ")
    other_office = crm.contact(principal=f"Todd {surname}")

    primary = crm.interaction(contact_id=linked.id)
    attendee_only = crm.interaction(attendee_contact_ids=[unlinked.id])
    both = crm.interaction(contact_id=linked.id, attendee_contact_ids=[unlinked.id])
    with_official = crm.interaction(contact_id=official.id)
    crm.interaction(contact_id=other_office.id)
    crm.interaction(organization_id=crm.org().id)

    items, total = list_interactions(
        db_session, page_num=0, page_size=25, principal=f"SARA {surname}"
    )
    assert total == 4
    assert sorted(str(i.id) for i in items) == sorted(
        str(i.id) for i in [primary, attendee_only, both, with_official]
    )


def test_crm_list_interactions_by_principal(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    staffer = crm.contact(principal=f"Sara {surname}")
    interaction = crm.interaction(contact_id=staffer.id)
    tool = CrmListTool(1, db_session, Emitter(Queue()))

    result = call(tool, entity_type="interaction", principal=f"sara {surname}")
    assert [i["id"] for i in result["results"]] == [str(interaction.id)]
    assert "similar_principals" not in result

    result = call(tool, entity_type="interaction", principal=f"Rep. Sara {surname}")
    assert result["total_items"] == 0
    assert result["similar_principals"] == [
        {"name": f"Sara {surname}", "contact_count": 1}
    ]


def test_link_sets_text_and_rename_updates_linked_staff(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    official = crm.contact(first_name="Sara", last_name=surname)
    created, _ = create_contact(
        db_session,
        first_name="Staffer",
        last_name=None,
        email=None,
        phone=None,
        title=None,
        organization_id=None,
        source=None,
        status="lead",
        notes=None,
        linkedin_url=None,
        location=None,
        created_by=None,
        principal="Rep. Jacobs",
        principal_contact_id=official.id,
    )
    crm.track(CrmContact, created.id)
    assert created.principal == f"Sara {surname}"

    patched = crm.contact(principal="someone else")
    update_contact(
        db_session, contact=patched, patches={"principal_contact_id": official.id}
    )
    assert patched.principal == f"Sara {surname}"
    unlinked = crm.contact(principal=f"Sara {surname}")
    before = stamp(db_session, CrmContact, patched.id)

    update_contact(db_session, contact=official, patches={"last_name": "Lee"})

    rows = dict(
        db_session.execute(
            select(CrmContact.id, CrmContact.principal).where(
                CrmContact.id.in_([created.id, patched.id, unlinked.id])
            )
        )
        .tuples()
        .all()
    )
    assert rows == {
        created.id: "Sara Lee",
        patched.id: "Sara Lee",
        unlinked.id: f"Sara {surname}",
    }
    assert stamp(db_session, CrmContact, patched.id) > before


def test_rename_waits_for_a_new_link_to_the_official(
    db_session: Session, crm: CrmRecords
) -> None:
    """A rename that ran while the link was uncommitted would miss the new
    staffer and leave it with the old name."""
    surname = unique_surname()
    official = crm.contact(first_name="Sara", last_name=surname)
    staffer = crm.contact()

    with (
        get_session_with_current_tenant() as linker,
        get_session_with_current_tenant() as renamer,
    ):
        update_contact(
            linker,
            contact=linker.get_one(CrmContact, staffer.id),
            patches={"principal_contact_id": official.id},
            commit=False,
        )
        _run_blocked_writer(
            db_session,
            holder=linker,
            writer=renamer,
            write=lambda session: update_contact(
                session,
                contact=session.get_one(CrmContact, official.id),
                patches={"last_name": "Lee"},
            ),
        )

    db_session.refresh(staffer)
    assert (staffer.principal, staffer.principal_contact_id) == (
        "Sara Lee",
        official.id,
    )


def test_rename_and_interaction_edit_do_not_deadlock(
    db_session: Session, crm: CrmRecords
) -> None:
    """An interaction edit touches its contacts in id order: here the staffer,
    then the official. A rename that locked the official before the staffer
    would deadlock with it."""
    staffer_id, official_id = sorted([uuid4(), uuid4()])
    official = crm.contact(id=official_id, first_name="Sara", last_name="Jacobs")
    staffer = crm.contact(
        id=staffer_id, principal="Sara Jacobs", principal_contact_id=official.id
    )

    with (
        get_session_with_current_tenant() as editor,
        get_session_with_current_tenant() as renamer,
    ):
        editor.execute(
            select(CrmContact.id)
            .where(CrmContact.id == staffer.id)
            .with_for_update(key_share=True)
        )
        _run_blocked_writer(
            db_session,
            holder=editor,
            writer=renamer,
            write=lambda session: update_contact(
                session,
                contact=session.get_one(CrmContact, official.id),
                patches={"last_name": "Lee"},
            ),
            holder_write=lambda session: session.execute(
                update(CrmContact)
                .where(CrmContact.id == official.id)
                .values(notes="touched")
            ),
        )

    db_session.refresh(staffer)
    assert staffer.principal == "Sara Lee"


def test_name_filter_ignores_principal(db_session: Session, crm: CrmRecords) -> None:
    surname = unique_surname()
    official = crm.contact(first_name="Sara", last_name=surname)
    crm.contact(principal=f"Sara {surname}")

    items, total = list_contacts(
        db_session, page_num=0, page_size=25, name=f"sara {surname[:-2]}"
    )
    assert (total, [c.id for c in items]) == (1, [official.id])


def test_principal_text_keeps_or_drops_the_link(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    official = crm.contact(first_name="Sara", last_name=surname)
    staffer = crm.contact(principal=f"Sara {surname}", principal_contact_id=official.id)

    _, changed = update_contact(
        db_session, contact=staffer, patches={"principal": f"SARA {surname}"}
    )
    assert not changed
    assert staffer.principal_contact_id == official.id

    update_contact(db_session, contact=staffer, patches={"principal": "Todd Young"})
    assert (staffer.principal, staffer.principal_contact_id) == ("Todd Young", None)

    update_contact(
        db_session, contact=staffer, patches={"principal_contact_id": official.id}
    )
    update_contact(db_session, contact=staffer, patches={"principal_contact_id": None})
    assert (staffer.principal, staffer.principal_contact_id) == (
        f"Sara {surname}",
        None,
    )


def test_deleting_official_keeps_staff_text(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    official = crm.contact(first_name="Sara", last_name=surname)
    staffer = crm.contact(principal=f"Sara {surname}", principal_contact_id=official.id)

    delete_contact(db_session, contact=official)
    db_session.refresh(staffer)
    assert (staffer.principal, staffer.principal_contact_id) == (
        f"Sara {surname}",
        None,
    )


def test_self_link_is_rejected(db_session: Session, crm: CrmRecords) -> None:
    contact = crm.contact()
    with pytest.raises(ValueError, match="its own principal"):
        update_contact(
            db_session, contact=contact, patches={"principal_contact_id": contact.id}
        )
    db_session.rollback()

    with pytest.raises(IntegrityError, match="ck_crm_contact_principal_not_self"):
        db_session.execute(
            update(CrmContact)
            .where(CrmContact.id == contact.id)
            .values(principal_contact_id=contact.id)
        )
    db_session.rollback()


def test_tools_link_principal_and_list_staff(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    official = crm.contact(first_name="Sara", last_name=surname)
    staffer = crm.contact(principal=f"Rep. Sara {surname}")
    crm.contact(principal=f"Sara {surname}")
    emitter = Emitter(Queue())
    update = CrmUpdateTool(1, db_session, emitter, str(crm.user().id))
    get = CrmGetTool(2, db_session, emitter)

    message = call_error(
        update,
        entity_type="contact",
        entity_id=str(staffer.id),
        updates={"principal_contact_id": str(uuid4())},
    )
    assert "'updates.principal_contact_id'" in message
    assert "Nothing was saved" in message

    updated = call(
        update,
        entity_type="contact",
        entity_id=str(staffer.id),
        updates={"principal_contact_id": str(official.id)},
    )
    assert updated["contact"]["principal"] == f"Sara {surname}"
    assert updated["contact"]["principal_contact_id"] == str(official.id)
    assert "similar_principals" not in updated

    result = call(
        get, entity_type="contact", entity_id=str(official.id), include=["staff"]
    )
    assert result["staff"]["total"] == 1
    assert [c["id"] for c in result["staff"]["items"]] == [str(staffer.id)]
