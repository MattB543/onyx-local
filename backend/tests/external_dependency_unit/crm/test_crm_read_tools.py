"""The CRM read tools (crm_list, crm_get, crm_search) and list_interactions
against a real, migrated Postgres: attendee-aware interaction lists, strict
filters, full pagination, and display names."""

import json
from datetime import datetime, timezone
from queue import Queue
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.crm import list_interactions
from onyx.db.enums import CrmInteractionType
from onyx.db.models import CrmContactOwner
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.crm.crm_get_tool import CrmGetTool
from onyx.tools.tool_implementations.crm.crm_list_tool import CrmListTool
from onyx.tools.tool_implementations.crm.crm_search_tool import CrmSearchTool
from tests.external_dependency_unit.crm.conftest import CrmRecords

PLACEMENT = Placement(turn_index=0, tab_index=0)
SAME_TIME = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


class ReadTools:
    def __init__(self, db_session: Session) -> None:
        emitter = Emitter(Queue())
        self.list = CrmListTool(1, db_session, emitter)
        self.get = CrmGetTool(2, db_session, emitter)
        self.search = CrmSearchTool(3, db_session, emitter)


@pytest.fixture
def tools(db_session: Session) -> ReadTools:
    return ReadTools(db_session)


def call(tool: Any, **kwargs: Any) -> dict[str, Any]:
    return json.loads(tool.run(placement=PLACEMENT, **kwargs).rich_response)


def call_model_view(tool: Any, **kwargs: Any) -> dict[str, Any]:
    """The compacted response the model actually sees."""
    return json.loads(tool.run(placement=PLACEMENT, **kwargs).llm_facing_response)


def call_error(tool: Any, **kwargs: Any) -> str:
    with pytest.raises(ToolCallException) as exc_info:
        tool.run(placement=PLACEMENT, **kwargs)
    return exc_info.value.llm_facing_message


def ids(rows: list[Any]) -> list[UUID]:
    return [row.id for row in rows]


def test_contact_interactions_include_attendee_only_without_duplicates(
    db_session: Session, crm: CrmRecords
) -> None:
    contact = crm.contact()
    as_primary = crm.interaction(contact_id=contact.id)
    as_both = crm.interaction(contact_id=contact.id, attendee_contact_ids=[contact.id])
    as_attendee = crm.interaction(
        attendee_contact_ids=[contact.id], type=CrmInteractionType.CALL
    )
    crm.interaction()  # unrelated

    items, total = list_interactions(
        db_session, page_num=0, page_size=25, contact_id=contact.id
    )
    assert total == 3
    assert sorted(ids(items)) == sorted([as_primary.id, as_both.id, as_attendee.id])

    items, total = list_interactions(
        db_session,
        page_num=0,
        page_size=25,
        contact_id=contact.id,
        interaction_type=CrmInteractionType.CALL,
    )
    assert (ids(items), total) == ([as_attendee.id], 1)


def test_organization_timeline_includes_member_attendee_interactions(
    db_session: Session, crm: CrmRecords
) -> None:
    org = crm.org()
    member = crm.contact(organization_id=org.id)
    other_member = crm.contact(organization_id=org.id)
    linked = crm.interaction(organization_id=org.id, attendee_contact_ids=[member.id])
    member_primary = crm.interaction(
        contact_id=member.id, attendee_contact_ids=[other_member.id]
    )
    member_attendee = crm.interaction(attendee_contact_ids=[member.id, other_member.id])
    crm.interaction()  # unrelated

    items, total = list_interactions(
        db_session,
        page_num=0,
        page_size=25,
        organization_id=org.id,
        include_contact_interactions=True,
    )
    assert total == 3
    assert sorted(ids(items)) == sorted(
        [linked.id, member_primary.id, member_attendee.id]
    )

    items, total = list_interactions(
        db_session, page_num=0, page_size=25, organization_id=org.id
    )
    assert (ids(items), total) == ([linked.id], 1)


def test_pagination_returns_every_interaction_once_despite_timestamp_ties(
    crm: CrmRecords, tools: ReadTools
) -> None:
    contact = crm.contact()
    created: list[UUID] = []
    for i in range(30):
        # Alternate primary contact and attendee-only; all share one time.
        interaction = (
            crm.interaction(occurred_at=SAME_TIME, contact_id=contact.id)
            if i % 2
            else crm.interaction(
                occurred_at=SAME_TIME, attendee_contact_ids=[contact.id]
            )
        )
        created.append(interaction.id)

    pages = [
        call_model_view(
            tools.list,
            entity_type="interaction",
            contact_id=str(contact.id),
            page_num=page_num,
            page_size=50,
        )
        for page_num in range(3)
    ]

    assert [page["page_size"] for page in pages] == [25, 25, 25]
    assert [page["total_items"] for page in pages] == [30, 30, 30]
    assert [len(page["results"]) for page in pages] == [25, 5, 0]
    # Equal times fall back to id order (descending), so paging is stable.
    seen = [item["id"] for page in pages for item in page["results"]]
    assert seen == [str(i) for i in sorted(created, reverse=True)]


def test_list_filters_interactions_by_contact_and_type(
    crm: CrmRecords, tools: ReadTools
) -> None:
    contact = crm.contact()
    crm.interaction(contact_id=contact.id, type=CrmInteractionType.NOTE)
    call_attended = crm.interaction(
        attendee_contact_ids=[contact.id], type=CrmInteractionType.CALL
    )
    crm.interaction(type=CrmInteractionType.CALL)  # other contact

    result = call(
        tools.list,
        entity_type="interaction",
        contact_id=str(contact.id),
        interaction_type="call",
    )

    assert result["total_items"] == 1
    assert [item["id"] for item in result["results"]] == [str(call_attended.id)]


def test_list_rejects_inapplicable_and_malformed_filters(
    crm: CrmRecords, tools: ReadTools
) -> None:
    tag = crm.tag()
    cases: list[tuple[dict[str, Any], str]] = [
        ({"entity_type": "organization", "status": "lead"}, "status"),
        ({"entity_type": "organization", "category": "Academic"}, "category"),
        ({"entity_type": "interaction", "sort_by": "created_at"}, "sort_by"),
        ({"entity_type": "interaction", "tag_ids": [str(tag.id)]}, "tag_ids"),
        ({"entity_type": "tag", "organization_id": str(tag.id)}, "organization_id"),
        ({"entity_type": "contact", "tag_ids": str(tag.id)}, "must be an array"),
        ({"entity_type": "contact", "tag_ids": []}, "empty"),
        ({"entity_type": "contact", "tag_ids": [None]}, "null"),
        ({"entity_type": "contact", "category": " "}, "category"),
        ({"entity_type": "contact", "organization_id": ""}, "organization_id"),
        ({"entity_type": "contact", "created_after": ""}, "created_after"),
        (
            {"entity_type": "interaction", "interaction_type": "lunch"},
            "interaction_type",
        ),
        ({"entity_type": "contact", "limit": 5}, "limit"),
    ]
    for kwargs, expected in cases:
        assert expected in call_error(tools.list, **kwargs), kwargs


def test_list_null_filters_count_as_omitted(tools: ReadTools) -> None:
    result = call(tools.list, entity_type="tag", status=None, page_size=None)
    assert result["status"] == "ok"


def test_list_and_get_include_names(
    db_session: Session, crm: CrmRecords, tools: ReadTools
) -> None:
    owner = crm.user()
    owner.personal_name = "Olive Owner"
    db_session.commit()
    org = crm.org()
    contact = crm.contact(first_name="Nia", last_name="Named", organization_id=org.id)
    attendee = crm.contact(first_name="Ada", last_name="Attendee")
    db_session.add(CrmContactOwner(contact_id=contact.id, user_id=owner.id))
    db_session.commit()
    interaction = crm.interaction(
        contact_id=contact.id,
        organization_id=org.id,
        logged_by=owner.id,
        attendee_contact_ids=[attendee.id],
        attendee_user_ids=[owner.id],
    )

    listed = call(tools.list, entity_type="contact", organization_id=str(org.id))
    (row,) = listed["results"]
    assert row["organization_name"] == org.name
    assert row["owners"] == [
        {"id": str(owner.id), "name": "Olive Owner", "email": owner.email}
    ]

    fetched = call(tools.get, entity_type="interaction", entity_id=str(interaction.id))
    item = fetched["interaction"]
    assert item["contact_name"] == "Nia Named"
    assert item["organization_name"] == org.name
    assert item["logged_by_name"] == "Olive Owner"
    assert sorted(a["display_name"] for a in item["attendees"]) == [
        "Ada Attendee",
        "Olive Owner",
    ]
    assert fetched["contact"]["owners"][0]["name"] == "Olive Owner"


def test_get_contact_names_its_principal_and_creator(
    db_session: Session, crm: CrmRecords, tools: ReadTools
) -> None:
    """X4: the model echoed principal_contact_id to the user. Each id the model
    sees on a contact now has the name next to it."""
    creator = crm.user()
    creator.personal_name = "Casey Creator"
    db_session.commit()
    official = crm.contact(first_name="Jane", last_name="Official")
    staffer = crm.contact(
        principal="Jane Official",
        principal_contact_id=official.id,
        created_by=creator.id,
    )

    contact = call_model_view(
        tools.get, entity_type="contact", entity_id=str(staffer.id)
    )["contact"]
    assert contact["principal_contact_id"] == str(official.id)
    assert contact["principal_contact_name"] == "Jane Official"
    assert contact["created_by"] == str(creator.id)
    assert contact["created_by_name"] == "Casey Creator"

    staff = call_model_view(
        tools.get,
        entity_type="contact",
        entity_id=str(official.id),
        include=["staff"],
    )["staff"]["items"]
    assert [row["principal_contact_name"] for row in staff] == ["Jane Official"]
    assert "UUIDs are for tool calls only" in tools.get.description


def test_get_contact_interactions_include_attendee_only(
    crm: CrmRecords, tools: ReadTools
) -> None:
    contact = crm.contact()
    interaction = crm.interaction(attendee_contact_ids=[contact.id])

    result = call(
        tools.get,
        entity_type="contact",
        entity_id=str(contact.id),
        include=["interactions", "tags"],
    )

    assert result["recent_interactions"]["total"] == 1
    assert result["recent_interactions"]["items"][0]["id"] == str(interaction.id)


@pytest.mark.parametrize(
    ("entity_type", "include", "expected"),
    [
        ("contact", ["contacts"], "contacts"),
        ("organization", ["organization"], "organization"),
        ("interaction", ["interactions"], "interactions"),
        ("contact", ["everything"], "everything"),
        ("contact", "interactions", "array"),
    ],
)
def test_get_rejects_invalid_or_inapplicable_includes(
    crm: CrmRecords,
    tools: ReadTools,
    entity_type: str,
    include: Any,
    expected: str,
) -> None:
    record_id = {
        "contact": lambda: crm.contact().id,
        "organization": lambda: crm.org().id,
        "interaction": lambda: crm.interaction().id,
    }[entity_type]()

    message = call_error(
        tools.get, entity_type=entity_type, entity_id=str(record_id), include=include
    )
    assert expected in message


def test_search_rejects_invalid_entity_types_and_caps_page_size(
    tools: ReadTools,
) -> None:
    for entity_types in (["contact", "people"], ["contact", {}], [["contact"]]):
        message = call_error(tools.search, query="anything", entity_types=entity_types)
        assert "Invalid 'entity_types'" in message

    result = call(tools.search, query="anything", page_size=50)
    assert result["page_size"] == 25


def test_search_pagination_returns_every_tied_result_once(
    crm: CrmRecords, tools: ReadTools
) -> None:
    token = f"tiebreak{uuid4().hex[:10]}"
    created = {
        str(crm.interaction(title=f"Sync {token}", occurred_at=SAME_TIME).id)
        for _ in range(30)
    }

    seen: list[str] = []
    for page_num in range(2):
        page = call_model_view(
            tools.search,
            query=token,
            entity_types=["interaction"],
            page_num=page_num,
            page_size=25,
        )
        assert page["total_items"] == 30
        seen.extend(result["entity_id"] for result in page["results"])

    assert len(seen) == 30
    assert set(seen) == created
