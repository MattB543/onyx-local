"""The CRM write tools (crm_create, crm_update, crm_log_interaction) against a
real, migrated Postgres: strict validation, one transaction per call, tag
changes, and fresh updated_at values in responses."""

import json
from datetime import datetime
from queue import Queue
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from psycopg2.errors import DeadlockDetected, LockNotAvailable
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.crm import replace_interaction_attendees
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import CrmAttendeeRole, CrmInteractionType
from onyx.db.models import (
    CrmContact,
    CrmContactOwner,
    CrmInteraction,
    CrmOrganization,
    User,
)
from onyx.server.features.crm.api import (
    add_contact_tag,
    add_organization_tag,
    post_interaction,
)
from onyx.server.features.crm.models import (
    CrmInteractionAttendeeInput,
    CrmInteractionCreateRequest,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.crm.attendee_resolution import resolve_attendees
from onyx.tools.tool_implementations.crm.crm_create_tool import CrmCreateTool
from onyx.tools.tool_implementations.crm.crm_get_tool import CrmGetTool
from onyx.tools.tool_implementations.crm.crm_log_interaction_tool import (
    CrmLogInteractionTool,
)
from onyx.tools.tool_implementations.crm.crm_update_tool import CrmUpdateTool
from onyx.tools.tool_implementations.crm.validation import crm_write_errors
from tests.external_dependency_unit.crm.conftest import CrmRecords, stamp

PLACEMENT = Placement(turn_index=0, tab_index=0)


class CrmTools:
    def __init__(self, db_session: Session, user: User) -> None:
        emitter = Emitter(Queue())
        user_id = str(user.id)
        self.user = user
        self.create = CrmCreateTool(1, db_session, emitter, user_id)
        self.update = CrmUpdateTool(2, db_session, emitter, user_id)
        self.log = CrmLogInteractionTool(3, db_session, emitter, user_id)
        self.get = CrmGetTool(4, db_session, emitter)


@pytest.fixture
def tools(db_session: Session, crm: CrmRecords) -> CrmTools:
    return CrmTools(db_session, crm.user())


def call(tool: Any, **kwargs: Any) -> dict[str, Any]:
    return json.loads(tool.run(placement=PLACEMENT, **kwargs).rich_response)


def call_error(tool: Any, **kwargs: Any) -> str:
    with pytest.raises(ToolCallException) as exc_info:
        tool.run(placement=PLACEMENT, **kwargs)
    return exc_info.value.llm_facing_message


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_report_sequence_for_contact_and_organization(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    """The bug report's seven-step check, through the real tools."""
    tag = crm.tag()
    email = f"report-{uuid4().hex[:8]}@example.com"

    # 1. A contact with no tags.
    created = call(
        tools.create,
        entity_type="contact",
        contact={"first_name": "Report", "last_name": "Sequence", "email": email},
    )
    contact_id = created["contact"]["id"]
    crm.track(CrmContact, contact_id)
    assert created["status"] == "created"
    assert created["contact"]["tags"] == []
    stamp_1 = ts(created["contact"]["updated_at"])

    # 2. Add a tag: crm_get shows it and a newer updated_at.
    added = call(
        tools.update,
        entity_type="contact",
        entity_id=contact_id,
        updates={"add_tag_ids": [str(tag.id)]},
    )
    assert added["status"] == "updated"
    assert added["tags_added"] == [{"id": str(tag.id), "name": tag.name}]
    fetched = call(tools.get, entity_type="contact", entity_id=contact_id)["contact"]
    assert [t["id"] for t in fetched["tags"]] == [str(tag.id)]
    stamp_2 = ts(fetched["updated_at"])
    assert stamp_2 > stamp_1
    assert ts(added["contact"]["updated_at"]) == stamp_2

    # 3. Remove it: gone, and updated_at moves again.
    removed = call(
        tools.update,
        entity_type="contact",
        entity_id=contact_id,
        updates={"remove_tag_ids": [str(tag.id)]},
    )
    assert removed["tags_removed"] == [{"id": str(tag.id), "name": tag.name}]
    fetched = call(tools.get, entity_type="contact", entity_id=contact_id)["contact"]
    assert fetched["tags"] == []
    stamp_3 = ts(fetched["updated_at"])
    assert stamp_3 > stamp_2

    # 4. Add a tag by hand in the app (REST): updated_at moves.
    add_contact_tag(UUID(contact_id), tag.id, db_session=db_session, _user=tools.user)
    fetched = call(tools.get, entity_type="contact", entity_id=contact_id)["contact"]
    assert ts(fetched["updated_at"]) > stamp_3

    # 5. Unknown field: an error that names it.
    message = call_error(
        tools.update,
        entity_type="contact",
        entity_id=contact_id,
        updates={"foo": 1},
    )
    assert "foo" in message

    # 6. Empty update: an error, not success.
    assert "empty" in call_error(
        tools.update, entity_type="contact", entity_id=contact_id, updates={}
    )

    # 7. Steps 2-4 for an organization.
    org = crm.org()
    org_stamp = stamp(db_session, CrmOrganization, org.id)
    added = call(
        tools.update,
        entity_type="organization",
        entity_id=str(org.id),
        updates={"add_tag_ids": [str(tag.id)]},
    )
    assert added["organization"]["tags"][0]["id"] == str(tag.id)
    org_added = ts(added["organization"]["updated_at"])
    assert org_added > org_stamp
    removed = call(
        tools.update,
        entity_type="organization",
        entity_id=str(org.id),
        updates={"remove_tag_ids": [str(tag.id)]},
    )
    assert removed["organization"]["tags"] == []
    org_removed = ts(removed["organization"]["updated_at"])
    assert org_removed > org_added
    add_organization_tag(org.id, tag.id, db_session=db_session, _user=tools.user)
    fetched = call(tools.get, entity_type="organization", entity_id=str(org.id))
    assert ts(fetched["organization"]["updated_at"]) > org_removed


def test_update_reports_no_changes(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    tag = crm.tag()
    contact = crm.contact(last_name="Same")
    call(
        tools.update,
        entity_type="contact",
        entity_id=str(contact.id),
        updates={"add_tag_ids": [str(tag.id)]},
    )
    before = stamp(db_session, CrmContact, contact.id)

    result = call(
        tools.update,
        entity_type="contact",
        entity_id=str(contact.id),
        updates={"last_name": " Same ", "add_tag_ids": [str(tag.id)]},
    )

    assert result["status"] == "no_changes"
    assert result["tags_added"] == []
    assert stamp(db_session, CrmContact, contact.id) == before


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"tag_ids": []}, "add_tag_ids"),
        ({"add_tag_ids": "not-a-list"}, "must be an array"),
        ({"add_tag_ids": [None, " "]}, "null"),
        ({"add_tag_ids": ["not-a-uuid"]}, "not-a-uuid"),
        ({"profile_picture_file_id": "file-1"}, "profile_picture_file_id"),
        (
            {
                "add_tag_ids": [
                    "11111111-1111-1111-1111-111111111111",
                    "11111111-1111-1111-1111-111111111111",
                ]
            },
            "more than once",
        ),
    ],
)
def test_update_rejects_bad_input(
    db_session: Session,
    crm: CrmRecords,
    tools: CrmTools,
    updates: dict[str, Any],
    expected: str,
) -> None:
    contact = crm.contact()
    message = call_error(
        tools.update,
        entity_type="contact",
        entity_id=str(contact.id),
        updates={"notes": "must not be saved", **updates},
    )
    assert expected in message
    notes = db_session.scalar(
        select(CrmContact.notes).where(CrmContact.id == contact.id)
    )
    assert notes is None


def test_update_rejects_missing_and_overlapping_tags_before_writing(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    contact = crm.contact()
    tag = crm.tag()
    missing_id = str(uuid4())

    message = call_error(
        tools.update,
        entity_type="contact",
        entity_id=str(contact.id),
        updates={"notes": "must not be saved", "add_tag_ids": [missing_id]},
    )
    assert missing_id in message

    message = call_error(
        tools.update,
        entity_type="contact",
        entity_id=str(contact.id),
        updates={"add_tag_ids": [str(tag.id)], "remove_tag_ids": [str(tag.id)]},
    )
    assert str(tag.id) in message

    notes = db_session.scalar(
        select(CrmContact.notes).where(CrmContact.id == contact.id)
    )
    assert notes is None


def test_mixed_update_rolls_back_when_a_later_write_fails(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    contact = crm.contact(last_name="Original")
    tag = crm.tag()
    before = stamp(db_session, CrmContact, contact.id)

    with patch(
        "onyx.tools.tool_implementations.crm.crm_update_tool.add_tag_to_contact",
        side_effect=IntegrityError("INSERT", {}, Exception("fk")),
    ):
        message = call_error(
            tools.update,
            entity_type="contact",
            entity_id=str(contact.id),
            updates={"last_name": "Changed", "add_tag_ids": [str(tag.id)]},
        )

    assert "Nothing was saved" in message
    last_name = db_session.scalar(
        select(CrmContact.last_name).where(CrmContact.id == contact.id)
    )
    assert last_name == "Original"
    assert stamp(db_session, CrmContact, contact.id) == before


def test_owner_ids_accept_teammate_email(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    contact = crm.contact()
    teammate = crm.user()

    result = call(
        tools.update,
        entity_type="contact",
        entity_id=str(contact.id),
        updates={"owner_ids": [teammate.email.upper(), str(tools.user.id)]},
    )
    assert set(result["contact"]["owner_ids"]) == {str(teammate.id), str(tools.user.id)}
    owners = set(
        db_session.scalars(
            select(CrmContactOwner.user_id).where(
                CrmContactOwner.contact_id == contact.id
            )
        )
    )
    assert owners == {teammate.id, tools.user.id}

    message = call_error(
        tools.update,
        entity_type="contact",
        entity_id=str(contact.id),
        updates={"owner_ids": ["nobody@example.invalid"]},
    )
    assert "nobody@example.invalid" in message


def test_create_already_exists_reports_not_applied_fields_and_adds_tags(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    email = f"exists-{uuid4().hex[:8]}@example.com"
    existing = crm.contact(first_name="Existing", email=email)
    tag = crm.tag()

    result = call(
        tools.create,
        entity_type="contact",
        contact={
            "first_name": "Other",
            "email": email.upper(),
            "title": "CEO",
            "tag_ids": [str(tag.id)],
        },
    )

    assert result["status"] == "already_exists"
    assert result["contact"]["id"] == str(existing.id)
    assert result["not_applied_fields"] == ["first_name", "title"]
    assert result["tags_added"] == [{"id": str(tag.id), "name": tag.name}]
    assert ts(result["contact"]["updated_at"]) == stamp(
        db_session, CrmContact, existing.id
    )

    tag_result = call(
        tools.create, entity_type="tag", tag={"name": tag.name.upper(), "color": "red"}
    )
    assert tag_result["status"] == "already_exists"
    assert tag_result["not_applied_fields"] == ["color"]
    assert "crm_update" not in tag_result["note"]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"contact": {"first_name": "X", "nickname": "Y"}}, "nickname"),
        (
            {"contact": {"first_name": "X"}, "organization": {"name": "Z"}},
            "organization",
        ),
        ({"contact": {"first_name": "X"}, "tag_ids": []}, "tag_ids"),
        ({"contact": {"first_name": "X", "tag_ids": ["bad"]}}, "bad"),
    ],
)
def test_create_rejects_bad_input_without_creating(
    db_session: Session, tools: CrmTools, kwargs: dict[str, Any], expected: str
) -> None:
    before = db_session.scalar(select(func.count()).select_from(CrmContact))

    message = call_error(tools.create, entity_type="contact", **kwargs)

    assert expected in message
    assert db_session.scalar(select(func.count()).select_from(CrmContact)) == before


def test_create_with_missing_tag_creates_nothing(
    db_session: Session, tools: CrmTools
) -> None:
    missing_id = str(uuid4())
    before = db_session.scalar(select(func.count()).select_from(CrmOrganization))

    message = call_error(
        tools.create,
        entity_type="organization",
        organization={"name": f"No Tag Org {uuid4().hex[:8]}", "tag_ids": [missing_id]},
    )

    assert missing_id in message
    assert (
        db_session.scalar(select(func.count()).select_from(CrmOrganization)) == before
    )


def test_log_interaction_links_warns_and_returns_fresh_stamp(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    primary = crm.contact()
    attendee = crm.contact(email=f"att-{uuid4().hex[:8]}@example.com")
    attendee_before = stamp(db_session, CrmContact, attendee.id)

    result = call(
        tools.log,
        title="Quarterly check-in",
        interaction_type="meeting",
        primary_contact_id=str(primary.id),
        attendees=[{"email": attendee.email}, {"name": f"Nobody {uuid4().hex}"}],
    )
    interaction_id = result["interaction"]["id"]
    crm.track(CrmInteraction, interaction_id)

    assert result["interaction"]["contact_id"] == str(primary.id)
    assert [a["contact_id"] for a in result["interaction"]["attendees"]] == [
        str(attendee.id)
    ]
    assert len(result["warnings"]) == 1
    assert "not_found" in result["warnings"][0]
    assert stamp(db_session, CrmContact, attendee.id) > attendee_before
    assert ts(result["interaction"]["updated_at"]) == stamp(
        db_session, CrmInteraction, UUID(interaction_id)
    )

    message = call_error(
        tools.log,
        title="Conflict",
        contact_id=str(primary.id),
        primary_contact_id=str(attendee.id),
    )
    assert "primary_contact_id" in message


def test_unchanged_attendee_replacement_is_a_no_op(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    attendee = crm.contact()
    interaction = crm.interaction(attendee_contact_ids=[attendee.id])
    attendee_before = stamp(db_session, CrmContact, attendee.id)
    interaction_before = stamp(db_session, CrmInteraction, interaction.id)

    result = call(
        tools.update,
        entity_type="interaction",
        entity_id=str(interaction.id),
        updates={"attendees": [{"contact_id": str(attendee.id)}]},
    )

    assert result["status"] == "no_changes"
    assert stamp(db_session, CrmContact, attendee.id) == attendee_before
    assert stamp(db_session, CrmInteraction, interaction.id) == interaction_before


def test_attendee_confidence_reflects_how_the_match_was_made(
    db_session: Session, crm: CrmRecords
) -> None:
    suffix = uuid4().hex[:8]
    contact = crm.contact(
        first_name=f"Jane{suffix}", last_name="Doe", email=f"jane.{suffix}@example.com"
    )

    _, _, details = resolve_attendees(
        db_session=db_session,
        attendees_to_resolve=[
            contact.email,
            f"{suffix}@example.com",
            f"Jane{suffix} Doe",
            f"jane{suffix}",
        ],
    )

    assert [detail["confidence"] for detail in details] == [
        "exact_email",
        "fuzzy_match",
        "exact_name",
        "fuzzy_match",
    ]


def test_rest_create_interaction_returns_fresh_stamp(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    contact = crm.contact()

    snapshot = post_interaction(
        CrmInteractionCreateRequest(
            type=CrmInteractionType.CALL,
            title="REST call",
            attendees=[
                CrmInteractionAttendeeInput(
                    contact_id=contact.id, role=CrmAttendeeRole.ATTENDEE
                )
            ],
        ),
        db_session=db_session,
        user=tools.user,
    )
    crm.track(CrmInteraction, snapshot.id)

    assert snapshot.updated_at == stamp(db_session, CrmInteraction, snapshot.id)


def test_retryable_database_errors_become_tool_errors() -> None:
    with pytest.raises(ToolCallException) as exc_info:
        with crm_write_errors("update"):
            raise OperationalError("UPDATE", {}, DeadlockDetected("deadlock"))

    assert "Retry the same call" in exc_info.value.llm_facing_message


def test_create_rolls_back_when_a_later_write_fails(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    tag = crm.tag()
    email = f"rollback-{uuid4().hex[:8]}@example.com"

    with patch(
        "onyx.tools.tool_implementations.crm.crm_create_tool.add_tag_to_contact",
        side_effect=IntegrityError("INSERT", {}, Exception("fk")),
    ):
        message = call_error(
            tools.create,
            entity_type="contact",
            contact={"first_name": "Roll", "email": email, "tag_ids": [str(tag.id)]},
        )

    assert "Nothing was saved" in message
    assert (
        db_session.scalar(select(CrmContact.id).where(CrmContact.email == email))
        is None
    )


def test_log_rolls_back_when_attendee_write_fails(
    db_session: Session, tools: CrmTools
) -> None:
    title = f"Rolled back {uuid4().hex[:8]}"

    with patch(
        "onyx.tools.tool_implementations.crm.crm_log_interaction_tool.replace_interaction_attendees",
        side_effect=IntegrityError("INSERT", {}, Exception("fk")),
    ):
        call_error(tools.log, title=title)

    assert (
        db_session.scalar(
            select(CrmInteraction.id).where(CrmInteraction.title == title)
        )
        is None
    )


def test_log_rejects_unknown_attendee_fields(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    contact = crm.contact()
    title = f"Misspelled {uuid4().hex[:8]}"

    message = call_error(
        tools.log,
        title=title,
        attendees=[{"contact_id": str(contact.id), "rol": "organizer"}],
    )

    assert "rol" in message
    assert (
        db_session.scalar(
            select(CrmInteraction.id).where(CrmInteraction.title == title)
        )
        is None
    )


def _open_transactions_elsewhere() -> int:
    with get_session_with_current_tenant() as session:
        return session.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                "AND state LIKE 'idle in transaction%'"
            )
        ).scalar_one()


def test_picture_download_holds_no_transaction_and_failed_write_deletes_it(
    db_session: Session, crm: CrmRecords, tools: CrmTools
) -> None:
    taken_email = f"taken-{uuid4().hex[:8]}@example.com"
    crm.contact(email=taken_email)
    contact = crm.contact()
    db_session.commit()
    open_during_download: list[int] = []

    def fake_download(*_args: Any, **_kwargs: Any) -> str:
        open_during_download.append(_open_transactions_elsewhere())
        return "file-downloaded"

    with (
        patch(
            "onyx.tools.tool_implementations.crm.crm_update_tool.save_file_from_url",
            side_effect=fake_download,
        ),
        patch(
            "onyx.tools.tool_implementations.crm.validation.get_default_file_store"
        ) as file_store,
    ):
        message = call_error(
            tools.update,
            entity_type="contact",
            entity_id=str(contact.id),
            updates={
                "profile_picture_url": "https://example.com/p.png",
                "email": taken_email,
            },
        )

    assert "already exists" in message
    assert open_during_download == [0]
    file_store.return_value.delete_file.assert_called_once_with(
        "file-downloaded", error_on_missing=False
    )


def test_attendee_replacement_locks_the_interaction(
    crm: CrmRecords,
) -> None:
    attendee = crm.contact()
    interaction = crm.interaction()

    with (
        get_session_with_current_tenant() as writer,
        get_session_with_current_tenant() as other,
    ):
        replace_interaction_attendees(
            writer,
            interaction_id=interaction.id,
            attendees=[(None, attendee.id, CrmAttendeeRole.ATTENDEE)],
            commit=False,
        )
        with pytest.raises(OperationalError) as exc_info:
            other.execute(
                select(CrmInteraction.id)
                .where(CrmInteraction.id == interaction.id)
                .with_for_update(key_share=True, nowait=True)
            )
        assert isinstance(exc_info.value.orig, LockNotAvailable)
        writer.rollback()
