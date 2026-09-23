"""Contact principal (the official a staffer works for) in list search, the
principal filter, the distinct-principal list, the CRM-wide search, and the
CRM tools."""

import json
from queue import Queue
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.crm import (
    find_similar_principals,
    list_contact_principals,
    list_contacts,
    search_crm_entities,
)
from onyx.db.models import CrmContact
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.tool_implementations.crm.crm_create_tool import CrmCreateTool
from onyx.tools.tool_implementations.crm.crm_list_tool import CrmListTool
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool
from tests.external_dependency_unit.crm.conftest import CrmRecords

PLACEMENT = Placement(turn_index=0, tab_index=0)


def call(tool: Any, **kwargs: Any) -> dict[str, Any]:
    return json.loads(tool.run(placement=PLACEMENT, **kwargs).rich_response)


def unique_surname() -> str:
    # Keeps other rows in the shared test DB out of the results.
    return f"Jacobs{uuid4().hex[:8]}"


def test_contact_search_and_filter_match_principal(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    principal = f"Sara {surname}"
    staffers = [
        crm.contact(principal=principal, title="Policy Advisor"),
        crm.contact(principal=principal),
        crm.contact(principal=f"  sara {surname.lower()} "),
    ]
    rep_titled = crm.contact(principal=f"Rep. Sara {surname}")
    crm.contact()

    items, total = list_contacts(db_session, page_num=0, page_size=25, query=principal)
    assert total == 4
    assert {c.id for c in items} == {c.id for c in [*staffers, rep_titled]}

    hits, total = search_crm_entities(
        db_session,
        query=principal,
        entity_types=["contact"],
        page_num=0,
        page_size=25,
    )
    assert total == 4
    assert {hit.entity_id for hit in hits} == {
        str(c.id) for c in [*staffers, rep_titled]
    }

    items, total = list_contacts(
        db_session, page_num=0, page_size=25, principal=f" {principal.upper()} "
    )
    assert total == 3
    assert {c.id for c in items} == {c.id for c in staffers}

    counts = {
        row.name: row.contact_count
        for row in list_contact_principals(db_session)
        if surname.lower() in row.name.lower()
    }
    assert counts == {principal: 3, f"Rep. Sara {surname}": 1}


def test_similar_principals_ignore_titles_and_exact_spelling(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    crm.contact(principal=f"Sara {surname}")
    crm.contact(principal=f"Sara {surname}")
    crm.contact(principal=f"Rep. Sara {surname}")
    crm.contact(principal=f"Sara {surname}son")

    similar = find_similar_principals(db_session, f"Congresswoman Sara {surname}")
    assert [(row.name, row.contact_count) for row in similar] == [
        (f"Sara {surname}", 2),
        (f"Rep. Sara {surname}", 1),
    ]
    # The exact spelling (any case) is not "similar" to itself.
    assert [
        row.name for row in find_similar_principals(db_session, f"sara {surname}")
    ] == [f"Rep. Sara {surname}"]


def test_crm_list_filters_by_principal_and_suggests_spellings(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    staffer = crm.contact(principal=f"Sara {surname}")
    crm.contact(principal=f"Todd {unique_surname()}")
    tool = CrmListTool(1, db_session, Emitter(Queue()))

    result = call(tool, entity_type="contact", principal=f"SARA {surname} ")
    assert result["total_items"] == 1
    assert [c["id"] for c in result["results"]] == [str(staffer.id)]
    assert "similar_principals" not in result

    result = call(tool, entity_type="contact", principal=f"Rep. Sara {surname}")
    assert result["total_items"] == 0
    assert result["similar_principals"] == [
        {"name": f"Sara {surname}", "contact_count": 1}
    ]


def test_crm_write_tools_flag_similar_principal(
    db_session: Session, crm: CrmRecords
) -> None:
    surname = unique_surname()
    crm.contact(principal=f"Sara {surname}")
    user_id = str(crm.user().id)
    emitter = Emitter(Queue())
    create = CrmCreateTool(1, db_session, emitter, user_id)
    update = CrmUpdateTool(2, db_session, emitter, user_id)

    created = call(
        create,
        entity_type="contact",
        contact={"first_name": "New", "principal": f"Rep. Sara {surname}"},
    )
    crm.track(CrmContact, created["contact"]["id"])
    assert created["similar_principals"] == [
        {"name": f"Sara {surname}", "contact_count": 1}
    ]

    updated = call(
        update,
        entity_type="contact",
        entity_id=created["contact"]["id"],
        updates={"principal": f"Sara {surname}"},
    )
    assert updated["contact"]["principal"] == f"Sara {surname}"
    assert "similar_principals" not in updated
