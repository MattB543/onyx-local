from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmInteractionType
from onyx.server.features.crm.api import _serialize_interaction
from onyx.server.features.crm.api import get_contacts
from onyx.server.features.crm.api import post_contact
from onyx.server.features.crm.api import post_interaction
from onyx.server.features.crm.models import CrmContactCreateRequest
from onyx.server.features.crm.models import CrmInteractionCreateRequest


def test_post_contact_defaults_owner_and_uses_workspace_default_stage() -> None:
    user_id = uuid4()
    db_session = MagicMock()
    request = CrmContactCreateRequest(first_name="Alice")
    created_contact = SimpleNamespace(id=uuid4())
    serialized_contact = {"id": str(created_contact.id)}

    with (
        patch(
            "onyx.server.features.crm.api.get_allowed_contact_stages",
            return_value=["prospect", "active"],
        ),
        patch("onyx.server.features.crm.api._ensure_user_exists") as mock_ensure_user_exists,
        patch(
            "onyx.server.features.crm.api.create_contact",
            return_value=(created_contact, True),
        ) as mock_create_contact,
        patch(
            "onyx.server.features.crm.api._serialize_contact",
            return_value=serialized_contact,
        ),
    ):
        result = post_contact(
            contact_create_request=request,
            db_session=db_session,
            user=SimpleNamespace(id=user_id),
        )

    assert result == serialized_contact
    mock_ensure_user_exists.assert_called_once_with(user_id, db_session)
    create_kwargs = mock_create_contact.call_args.kwargs
    assert create_kwargs["owner_ids"] == [user_id]
    assert create_kwargs["status"] == "prospect"


def test_post_contact_explicit_null_owner_ids_keeps_contact_unowned() -> None:
    db_session = MagicMock()
    request = CrmContactCreateRequest(
        first_name="Alice",
        owner_ids=None,
        status="active",
    )
    created_contact = SimpleNamespace(id=uuid4())
    serialized_contact = {"id": str(created_contact.id)}

    with (
        patch(
            "onyx.server.features.crm.api.get_allowed_contact_stages",
            return_value=["lead", "active"],
        ),
        patch("onyx.server.features.crm.api._ensure_user_exists") as mock_ensure_user_exists,
        patch(
            "onyx.server.features.crm.api.create_contact",
            return_value=(created_contact, True),
        ) as mock_create_contact,
        patch(
            "onyx.server.features.crm.api._serialize_contact",
            return_value=serialized_contact,
        ),
    ):
        result = post_contact(
            contact_create_request=request,
            db_session=db_session,
            user=SimpleNamespace(id=uuid4()),
        )

    assert result == serialized_contact
    mock_ensure_user_exists.assert_not_called()
    create_kwargs = mock_create_contact.call_args.kwargs
    assert create_kwargs["owner_ids"] == []
    assert create_kwargs["status"] == "active"


def test_get_contacts_rejects_stage_not_in_workspace_settings() -> None:
    with patch(
        "onyx.server.features.crm.api.get_allowed_contact_stages",
        return_value=["lead", "active"],
    ):
        with pytest.raises(HTTPException) as exc:
            get_contacts(
                status="unknown",
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 400
    assert "'status' must be one of" in str(exc.value.detail)


def test_post_interaction_omitted_attendees_adds_actor_and_primary_contact() -> None:
    user_id = uuid4()
    contact_id = uuid4()
    interaction_id = uuid4()
    request = CrmInteractionCreateRequest(
        contact_id=contact_id,
        type=CrmInteractionType.NOTE,
        title="Follow-up",
    )
    serialized_interaction = {"id": str(interaction_id)}
    db_session = MagicMock()

    with (
        patch("onyx.server.features.crm.api._load_contact_or_404"),
        patch(
            "onyx.server.features.crm.api.create_interaction",
            return_value=SimpleNamespace(id=interaction_id),
        ),
        patch(
            "onyx.server.features.crm.api.add_interaction_attendees"
        ) as mock_add_attendees,
        patch(
            "onyx.server.features.crm.api._serialize_interaction",
            return_value=serialized_interaction,
        ),
    ):
        result = post_interaction(
            interaction_create_request=request,
            db_session=db_session,
            user=SimpleNamespace(id=user_id),
        )

    assert result == serialized_interaction
    assert mock_add_attendees.call_count == 2

    calls_by_role = {
        call.kwargs["role"]: call.kwargs for call in mock_add_attendees.call_args_list
    }
    assert calls_by_role[CrmAttendeeRole.ORGANIZER]["user_ids"] == [user_id]
    assert calls_by_role[CrmAttendeeRole.ORGANIZER]["contact_ids"] is None
    assert calls_by_role[CrmAttendeeRole.ATTENDEE]["user_ids"] is None
    assert calls_by_role[CrmAttendeeRole.ATTENDEE]["contact_ids"] == [contact_id]


def test_post_interaction_explicit_empty_attendees_adds_no_defaults() -> None:
    request = CrmInteractionCreateRequest(
        contact_id=uuid4(),
        type=CrmInteractionType.CALL,
        title="Weekly call",
        attendees=[],
    )
    db_session = MagicMock()

    with (
        patch("onyx.server.features.crm.api._load_contact_or_404"),
        patch(
            "onyx.server.features.crm.api.create_interaction",
            return_value=SimpleNamespace(id=uuid4()),
        ),
        patch(
            "onyx.server.features.crm.api.add_interaction_attendees"
        ) as mock_add_attendees,
        patch(
            "onyx.server.features.crm.api._serialize_interaction",
            return_value={"id": "interaction"},
        ),
    ):
        post_interaction(
            interaction_create_request=request,
            db_session=db_session,
            user=SimpleNamespace(id=uuid4()),
        )

    mock_add_attendees.assert_not_called()


def test_post_interaction_explicit_null_attendees_adds_no_defaults() -> None:
    request = CrmInteractionCreateRequest(
        contact_id=uuid4(),
        type=CrmInteractionType.EMAIL,
        title="Async update",
        attendees=None,
    )
    db_session = MagicMock()

    with (
        patch("onyx.server.features.crm.api._load_contact_or_404"),
        patch(
            "onyx.server.features.crm.api.create_interaction",
            return_value=SimpleNamespace(id=uuid4()),
        ),
        patch(
            "onyx.server.features.crm.api.add_interaction_attendees"
        ) as mock_add_attendees,
        patch(
            "onyx.server.features.crm.api._serialize_interaction",
            return_value={"id": "interaction"},
        ),
    ):
        post_interaction(
            interaction_create_request=request,
            db_session=db_session,
            user=SimpleNamespace(id=uuid4()),
        )

    mock_add_attendees.assert_not_called()


def test_serialize_interaction_includes_attendee_display_names() -> None:
    now = datetime.now(timezone.utc)
    interaction_id = uuid4()
    attendee_user_id = uuid4()
    attendee_contact_id = uuid4()

    interaction = SimpleNamespace(
        id=interaction_id,
        contact_id=None,
        organization_id=None,
        logged_by=attendee_user_id,
        type=CrmInteractionType.MEETING,
        title="Quarterly sync",
        summary="Reviewed roadmap",
        occurred_at=now,
        created_at=now,
        updated_at=now,
    )
    attendee_user = SimpleNamespace(
        id=1,
        user_id=attendee_user_id,
        contact_id=None,
        role=CrmAttendeeRole.ORGANIZER,
        created_at=now,
    )
    attendee_contact = SimpleNamespace(
        id=2,
        user_id=None,
        contact_id=attendee_contact_id,
        role=CrmAttendeeRole.ATTENDEE,
        created_at=now,
    )
    attendee_user_model = SimpleNamespace(
        personal_name="Alex Smith",
        email="alex@example.com",
    )
    attendee_contact_model = SimpleNamespace(
        first_name="Sam",
        last_name="Lee",
        email="sam@example.com",
    )
    db_session = MagicMock()

    def _mock_get(model, id):  # noqa: ANN001, ANN202
        if id == attendee_user_id:
            return attendee_user_model
        return None

    db_session.get.side_effect = _mock_get

    with (
        patch(
            "onyx.server.features.crm.api.get_interaction_attendees",
            return_value=[attendee_user, attendee_contact],
        ),
        patch(
            "onyx.server.features.crm.api.get_contact_by_id",
            return_value=attendee_contact_model,
        ),
    ):
        serialized = _serialize_interaction(interaction, db_session)

    assert [a.display_name for a in serialized.attendees] == ["Alex Smith", "Sam Lee"]
