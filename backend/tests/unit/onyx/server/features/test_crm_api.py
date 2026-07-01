import asyncio
from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import call
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from onyx.configs.constants import FileOrigin
from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmInteractionType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.crm.api import _delete_file_best_effort
from onyx.server.features.crm.api import _serialize_interaction
from onyx.server.features.crm.api import current_admin_user
from onyx.server.features.crm.api import current_user
from onyx.server.features.crm.api import delete_contact_profile_picture
from onyx.server.features.crm.api import delete_crm_contact
from onyx.server.features.crm.api import delete_crm_interaction
from onyx.server.features.crm.api import delete_crm_organization
from onyx.server.features.crm.api import get_contacts
from onyx.server.features.crm.api import get_organizations
from onyx.server.features.crm.api import get_session
from onyx.server.features.crm.api import import_contacts_csv
from onyx.server.features.crm.api import patch_interaction
from onyx.server.features.crm.api import post_contact
from onyx.server.features.crm.api import post_interaction
from onyx.server.features.crm.api import router
from onyx.server.features.crm.api import upload_contact_profile_picture
from onyx.server.features.crm.models import CrmContactCreateRequest
from onyx.server.features.crm.models import CrmContactSnapshot
from onyx.server.features.crm.models import CrmInteractionAttendeeInput
from onyx.server.features.crm.models import CrmInteractionCreateRequest
from onyx.server.features.crm.models import CrmInteractionPatchRequest


def _build_crm_test_client(
    *,
    override_admin_user,  # noqa: ANN001
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: MagicMock()
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_admin_user] = override_admin_user
    return TestClient(app, raise_server_exceptions=False)


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
        patch(
            "onyx.server.features.crm.api._ensure_user_exists"
        ) as mock_ensure_user_exists,
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
        patch(
            "onyx.server.features.crm.api._ensure_user_exists"
        ) as mock_ensure_user_exists,
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


def test_contact_create_request_allows_last_name_only() -> None:
    request = CrmContactCreateRequest(last_name="Smith")

    assert request.first_name is None
    assert request.last_name == "Smith"


def test_contact_create_request_rejects_no_names() -> None:
    with pytest.raises(ValidationError, match="first name or a last name"):
        CrmContactCreateRequest()


def test_contact_snapshot_last_name_only_builds_full_name() -> None:
    now = datetime.now(timezone.utc)
    contact = SimpleNamespace(
        id=uuid4(),
        first_name=None,
        last_name="Smith",
        email=None,
        phone=None,
        title=None,
        organization_id=None,
        source=None,
        status="lead",
        category=None,
        party_affiliation=None,
        us_state=None,
        principal=None,
        notes=None,
        linkedin_url=None,
        location=None,
        profile_picture_file_id=None,
        created_by=None,
        created_at=now,
        updated_at=now,
    )

    snapshot = CrmContactSnapshot.from_model(contact=contact, owner_ids=[], tags=[])

    assert snapshot.first_name is None
    assert snapshot.last_name == "Smith"
    assert snapshot.full_name == "Smith"


def test_contact_snapshot_profile_picture_url_none_when_no_file_id() -> None:
    now = datetime.now(timezone.utc)
    contact = SimpleNamespace(
        id=uuid4(),
        first_name="Bob",
        last_name="Jones",
        email="bob@example.com",
        phone=None,
        title=None,
        organization_id=None,
        source=None,
        status="lead",
        category=None,
        party_affiliation=None,
        us_state=None,
        principal=None,
        notes=None,
        linkedin_url=None,
        location=None,
        profile_picture_file_id=None,
        created_by=None,
        created_at=now,
        updated_at=now,
    )

    snapshot = CrmContactSnapshot.from_model(contact=contact, owner_ids=[], tags=[])

    assert snapshot.profile_picture_file_id is None
    assert snapshot.profile_picture_url is None


def test_contact_snapshot_includes_profile_picture_fields() -> None:
    now = datetime.now(timezone.utc)
    contact = SimpleNamespace(
        id=uuid4(),
        first_name="Alice",
        last_name="Smith",
        email="alice@example.com",
        phone=None,
        title=None,
        organization_id=None,
        source=None,
        status="lead",
        category=None,
        party_affiliation=None,
        us_state=None,
        principal=None,
        notes=None,
        linkedin_url=None,
        location=None,
        profile_picture_file_id="file-123",
        created_by=None,
        created_at=now,
        updated_at=now,
    )

    snapshot = CrmContactSnapshot.from_model(contact=contact, owner_ids=[], tags=[])

    assert snapshot.profile_picture_file_id == "file-123"
    assert snapshot.profile_picture_url == "/api/chat/file/file-123"


def test_contact_snapshot_includes_organization_name() -> None:
    now = datetime.now(timezone.utc)
    contact = SimpleNamespace(
        id=uuid4(),
        first_name="Alice",
        last_name="Smith",
        email="alice@example.com",
        phone=None,
        title=None,
        organization_id=uuid4(),
        source=None,
        status="lead",
        category=None,
        party_affiliation=None,
        us_state=None,
        principal=None,
        notes=None,
        linkedin_url=None,
        location=None,
        profile_picture_file_id=None,
        created_by=None,
        created_at=now,
        updated_at=now,
    )

    snapshot = CrmContactSnapshot.from_model(
        contact=contact,
        owner_ids=[],
        organization_name="Acme Corp",
        tags=[],
    )

    assert snapshot.organization_name == "Acme Corp"


def test_get_contacts_rejects_stage_not_in_workspace_settings() -> None:
    with patch(
        "onyx.server.features.crm.api.get_allowed_contact_stages",
        return_value=["lead", "active"],
    ):
        with pytest.raises(OnyxError) as exc:
            get_contacts(
                status="unknown",
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 400
    assert "'status' must be one of" in str(exc.value.detail)


def test_upload_contact_profile_picture_updates_contact() -> None:
    contact_id = uuid4()
    db_session = MagicMock()
    file_store = MagicMock()
    file_store.save_file.return_value = "file-123"
    upload = SimpleNamespace(
        content_type="image/png",
        file=MagicMock(),
        filename="avatar.png",
    )
    contact = SimpleNamespace(id=contact_id, profile_picture_file_id=None)

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch(
            "onyx.server.features.crm.api.is_upload_too_large",
            return_value=False,
        ),
        patch(
            "onyx.server.features.crm.api.get_default_file_store",
            return_value=file_store,
        ),
        patch("onyx.server.features.crm.api.update_contact") as mock_update_contact,
    ):
        result = upload_contact_profile_picture(
            contact_id=contact_id,
            file=upload,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert result == {"file_id": "file-123"}
    file_store.save_file.assert_called_once()
    mock_update_contact.assert_called_once_with(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": "file-123"},
    )


def test_upload_contact_profile_picture_replaces_existing_blob() -> None:
    contact_id = uuid4()
    db_session = MagicMock()
    file_store = MagicMock()
    file_store.save_file.return_value = "file-456"
    upload = SimpleNamespace(
        content_type="image/png",
        file=MagicMock(),
        filename="avatar.png",
    )
    contact = SimpleNamespace(id=contact_id, profile_picture_file_id="file-123")

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch(
            "onyx.server.features.crm.api.is_upload_too_large",
            return_value=False,
        ),
        patch(
            "onyx.server.features.crm.api.get_default_file_store",
            return_value=file_store,
        ),
        patch("onyx.server.features.crm.api.update_contact"),
        patch(
            "onyx.server.features.crm.api._delete_file_best_effort"
        ) as mock_delete_file,
    ):
        result = upload_contact_profile_picture(
            contact_id=contact_id,
            file=upload,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert result == {"file_id": "file-456"}
    mock_delete_file.assert_called_once_with("file-123")


def test_upload_contact_profile_picture_cleans_up_new_blob_if_update_fails() -> None:
    contact_id = uuid4()
    db_session = MagicMock()
    file_store = MagicMock()
    file_store.save_file.return_value = "file-456"
    upload = SimpleNamespace(
        content_type="image/png",
        file=MagicMock(),
        filename="avatar.png",
    )
    contact = SimpleNamespace(id=contact_id, profile_picture_file_id="file-123")

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch(
            "onyx.server.features.crm.api.is_upload_too_large",
            return_value=False,
        ),
        patch(
            "onyx.server.features.crm.api.get_default_file_store",
            return_value=file_store,
        ),
        patch(
            "onyx.server.features.crm.api.update_contact",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "onyx.server.features.crm.api._delete_file_best_effort"
        ) as mock_delete_file,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            upload_contact_profile_picture(
                contact_id=contact_id,
                file=upload,
                db_session=db_session,
                _user=SimpleNamespace(id=uuid4()),
            )

    mock_delete_file.assert_called_once_with("file-456")


def test_upload_contact_profile_picture_normalizes_content_type_and_filename() -> None:
    contact_id = uuid4()
    db_session = MagicMock()
    file_store = MagicMock()
    file_store.save_file.return_value = "file-123"
    upload = SimpleNamespace(
        content_type="image/jpeg; charset=utf-8",
        file=MagicMock(),
        filename=None,
    )
    contact = SimpleNamespace(id=contact_id, profile_picture_file_id=None)

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch(
            "onyx.server.features.crm.api.is_upload_too_large",
            return_value=False,
        ),
        patch(
            "onyx.server.features.crm.api.get_default_file_store",
            return_value=file_store,
        ),
        patch("onyx.server.features.crm.api.update_contact"),
    ):
        upload_contact_profile_picture(
            contact_id=contact_id,
            file=upload,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    save_kwargs = file_store.save_file.call_args.kwargs
    assert save_kwargs["display_name"] == f"crm_profile_{contact_id}"
    assert save_kwargs["file_origin"] == FileOrigin.CRM_UPLOAD
    assert save_kwargs["file_type"] == "image/jpeg"


def test_upload_contact_profile_picture_rejects_non_image_mime_type() -> None:
    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=SimpleNamespace(id=uuid4()),
        ),
    ):
        with pytest.raises(OnyxError) as exc:
            upload_contact_profile_picture(
                contact_id=uuid4(),
                file=SimpleNamespace(
                    content_type="text/plain",
                    file=MagicMock(),
                    filename="notes.txt",
                ),
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 400
    assert "Only image uploads are supported" in str(exc.value.detail)


def test_upload_contact_profile_picture_missing_contact_raises_not_found() -> None:
    not_found = OnyxError(OnyxErrorCode.NOT_FOUND, "CRM contact not found.")

    with patch(
        "onyx.server.features.crm.api._load_contact_or_404",
        side_effect=not_found,
    ):
        with pytest.raises(OnyxError) as exc:
            upload_contact_profile_picture(
                contact_id=uuid4(),
                file=SimpleNamespace(
                    content_type="image/png",
                    file=MagicMock(),
                    filename="avatar.png",
                ),
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 404


def test_upload_contact_profile_picture_rejects_oversized_upload() -> None:
    db_session = MagicMock()
    file_store = MagicMock()

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=SimpleNamespace(id=uuid4()),
        ),
        patch(
            "onyx.server.features.crm.api.is_upload_too_large",
            return_value=True,
        ),
        patch(
            "onyx.server.features.crm.api.get_default_file_store",
            return_value=file_store,
        ),
        patch("onyx.server.features.crm.api.update_contact") as mock_update_contact,
    ):
        with pytest.raises(OnyxError) as exc:
            upload_contact_profile_picture(
                contact_id=uuid4(),
                file=SimpleNamespace(
                    content_type="image/png",
                    file=MagicMock(),
                    filename="avatar.png",
                ),
                db_session=db_session,
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 400
    assert "maximum allowed size" in str(exc.value.detail)
    file_store.save_file.assert_not_called()
    mock_update_contact.assert_not_called()


def test_delete_contact_profile_picture_clears_picture() -> None:
    db_session = MagicMock()
    contact = SimpleNamespace(id=uuid4(), profile_picture_file_id="file-123")

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch("onyx.server.features.crm.api.update_contact") as mock_update_contact,
        patch(
            "onyx.server.features.crm.api._delete_file_best_effort"
        ) as mock_delete_file,
    ):
        response = delete_contact_profile_picture(
            contact_id=contact.id,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert response.status_code == 204
    mock_update_contact.assert_called_once_with(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": None},
    )
    mock_delete_file.assert_called_once_with("file-123")


def test_delete_contact_profile_picture_without_existing_picture_is_safe() -> None:
    db_session = MagicMock()
    contact = SimpleNamespace(id=uuid4(), profile_picture_file_id=None)

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch("onyx.server.features.crm.api.update_contact") as mock_update_contact,
        patch(
            "onyx.server.features.crm.api._delete_file_best_effort"
        ) as mock_delete_file,
    ):
        response = delete_contact_profile_picture(
            contact_id=contact.id,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert response.status_code == 204
    mock_update_contact.assert_called_once_with(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": None},
    )
    mock_delete_file.assert_called_once_with(None)


def test_delete_crm_contact_deletes_contact_and_blob() -> None:
    db_session = MagicMock()
    contact = SimpleNamespace(id=uuid4(), profile_picture_file_id="file-123")

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch("onyx.server.features.crm.api.delete_contact") as mock_delete_contact,
        patch(
            "onyx.server.features.crm.api._delete_file_best_effort"
        ) as mock_delete_file,
    ):
        call_order = MagicMock()
        call_order.attach_mock(mock_delete_contact, "delete_contact")
        call_order.attach_mock(mock_delete_file, "delete_file")
        response = delete_crm_contact(
            contact_id=contact.id,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert response.status_code == 204
    mock_delete_contact.assert_called_once_with(db_session=db_session, contact=contact)
    mock_delete_file.assert_called_once_with("file-123")
    assert call_order.mock_calls == [
        call.delete_contact(db_session=db_session, contact=contact),
        call.delete_file("file-123"),
    ]


def test_delete_crm_contact_without_profile_picture_is_safe() -> None:
    db_session = MagicMock()
    contact = SimpleNamespace(id=uuid4(), profile_picture_file_id=None)

    with (
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            return_value=contact,
        ),
        patch("onyx.server.features.crm.api.delete_contact") as mock_delete_contact,
        patch(
            "onyx.server.features.crm.api._delete_file_best_effort"
        ) as mock_delete_file,
    ):
        response = delete_crm_contact(
            contact_id=contact.id,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert response.status_code == 204
    mock_delete_contact.assert_called_once_with(db_session=db_session, contact=contact)
    mock_delete_file.assert_called_once_with(None)


def test_delete_crm_organization_deletes_organization() -> None:
    db_session = MagicMock()
    organization = SimpleNamespace(id=uuid4())

    with (
        patch(
            "onyx.server.features.crm.api._load_organization_or_404",
            return_value=organization,
        ),
        patch(
            "onyx.server.features.crm.api.delete_organization"
        ) as mock_delete_organization,
    ):
        response = delete_crm_organization(
            organization_id=organization.id,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert response.status_code == 204
    mock_delete_organization.assert_called_once_with(
        db_session=db_session,
        organization=organization,
    )


def test_delete_crm_interaction_deletes_interaction() -> None:
    db_session = MagicMock()
    interaction = SimpleNamespace(id=uuid4())

    with (
        patch(
            "onyx.server.features.crm.api._load_interaction_or_404",
            return_value=interaction,
        ),
        patch(
            "onyx.server.features.crm.api.delete_interaction"
        ) as mock_delete_interaction,
    ):
        response = delete_crm_interaction(
            interaction_id=interaction.id,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert response.status_code == 204
    mock_delete_interaction.assert_called_once_with(
        db_session=db_session,
        interaction=interaction,
    )


def test_delete_crm_contact_missing_contact_raises_not_found() -> None:
    not_found = OnyxError(OnyxErrorCode.NOT_FOUND, "CRM contact not found.")

    with patch(
        "onyx.server.features.crm.api._load_contact_or_404",
        side_effect=not_found,
    ):
        with pytest.raises(OnyxError) as exc:
            delete_crm_contact(
                contact_id=uuid4(),
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 404


def test_delete_crm_organization_missing_organization_raises_not_found() -> None:
    not_found = OnyxError(OnyxErrorCode.NOT_FOUND, "CRM organization not found.")

    with patch(
        "onyx.server.features.crm.api._load_organization_or_404",
        side_effect=not_found,
    ):
        with pytest.raises(OnyxError) as exc:
            delete_crm_organization(
                organization_id=uuid4(),
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 404


def test_delete_crm_interaction_missing_interaction_raises_not_found() -> None:
    not_found = OnyxError(OnyxErrorCode.NOT_FOUND, "CRM interaction not found.")

    with patch(
        "onyx.server.features.crm.api._load_interaction_or_404",
        side_effect=not_found,
    ):
        with pytest.raises(OnyxError) as exc:
            delete_crm_interaction(
                interaction_id=uuid4(),
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 404


def test_delete_file_best_effort_noops_on_missing_file_id() -> None:
    with patch(
        "onyx.server.features.crm.api.get_default_file_store"
    ) as mock_get_default_file_store:
        _delete_file_best_effort(None)

    mock_get_default_file_store.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        f"/user/crm/contacts/{uuid4()}",
        f"/user/crm/organizations/{uuid4()}",
        f"/user/crm/interactions/{uuid4()}",
    ],
)
def test_delete_routes_require_admin_user(path: str) -> None:
    client = _build_crm_test_client(
        override_admin_user=lambda: (_ for _ in ()).throw(
            HTTPException(status_code=403, detail="Admin only")
        )
    )

    response = client.delete(path)

    assert response.status_code == 403


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


def test_patch_interaction_updates_basic_fields() -> None:
    interaction_id = uuid4()
    occurred_at = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    request = CrmInteractionPatchRequest(
        title="Updated title",
        summary="Updated summary",
        occurred_at=occurred_at,
    )
    interaction = SimpleNamespace(id=interaction_id)
    db_session = MagicMock()

    with (
        patch(
            "onyx.server.features.crm.api._load_interaction_or_404",
            return_value=interaction,
        ),
        patch(
            "onyx.server.features.crm.api.update_interaction"
        ) as mock_update_interaction,
        patch(
            "onyx.server.features.crm.api.replace_interaction_attendees"
        ) as mock_replace_attendees,
        patch(
            "onyx.server.features.crm.api._serialize_interaction",
            return_value={"id": str(interaction_id)},
        ),
    ):
        result = patch_interaction(
            interaction_id=interaction_id,
            interaction_patch_request=request,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    assert result == {"id": str(interaction_id)}
    mock_update_interaction.assert_called_once()
    patches = mock_update_interaction.call_args.kwargs["patches"]
    assert patches == {
        "title": "Updated title",
        "summary": "Updated summary",
        "occurred_at": occurred_at,
    }
    mock_replace_attendees.assert_not_called()


def test_patch_interaction_clears_occurred_at() -> None:
    interaction_id = uuid4()
    request = CrmInteractionPatchRequest(occurred_at=None)
    db_session = MagicMock()

    with (
        patch(
            "onyx.server.features.crm.api._load_interaction_or_404",
            return_value=SimpleNamespace(id=interaction_id),
        ),
        patch(
            "onyx.server.features.crm.api.update_interaction"
        ) as mock_update_interaction,
        patch(
            "onyx.server.features.crm.api._serialize_interaction",
            return_value={"id": str(interaction_id)},
        ),
    ):
        patch_interaction(
            interaction_id=interaction_id,
            interaction_patch_request=request,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    patches = mock_update_interaction.call_args.kwargs["patches"]
    assert "occurred_at" in patches
    assert patches["occurred_at"] is None


def test_patch_interaction_rejects_null_title() -> None:
    request = CrmInteractionPatchRequest(title=None)

    with patch(
        "onyx.server.features.crm.api._load_interaction_or_404",
        return_value=SimpleNamespace(id=uuid4()),
    ):
        with pytest.raises(OnyxError) as exc:
            patch_interaction(
                interaction_id=uuid4(),
                interaction_patch_request=request,
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR


def test_patch_interaction_validates_contact_id() -> None:
    contact_id = uuid4()
    request = CrmInteractionPatchRequest(contact_id=contact_id)
    not_found = OnyxError(OnyxErrorCode.NOT_FOUND, "CRM contact not found.")

    with (
        patch(
            "onyx.server.features.crm.api._load_interaction_or_404",
            return_value=SimpleNamespace(id=uuid4()),
        ),
        patch(
            "onyx.server.features.crm.api._load_contact_or_404",
            side_effect=not_found,
        ),
    ):
        with pytest.raises(OnyxError) as exc:
            patch_interaction(
                interaction_id=uuid4(),
                interaction_patch_request=request,
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 404


def test_patch_interaction_replaces_attendees() -> None:
    interaction_id = uuid4()
    attendee_contact_id = uuid4()
    request = CrmInteractionPatchRequest(
        attendees=[
            CrmInteractionAttendeeInput(
                contact_id=attendee_contact_id,
                role=CrmAttendeeRole.ATTENDEE,
            )
        ]
    )
    db_session = MagicMock()

    with (
        patch(
            "onyx.server.features.crm.api._load_interaction_or_404",
            return_value=SimpleNamespace(id=interaction_id),
        ),
        patch("onyx.server.features.crm.api.update_interaction"),
        patch(
            "onyx.server.features.crm.api.get_contact_by_id",
            return_value=SimpleNamespace(id=attendee_contact_id),
        ),
        patch(
            "onyx.server.features.crm.api.replace_interaction_attendees"
        ) as mock_replace_attendees,
        patch(
            "onyx.server.features.crm.api._serialize_interaction",
            return_value={"id": str(interaction_id)},
        ),
    ):
        patch_interaction(
            interaction_id=interaction_id,
            interaction_patch_request=request,
            db_session=db_session,
            _user=SimpleNamespace(id=uuid4()),
        )

    mock_replace_attendees.assert_called_once()
    kwargs = mock_replace_attendees.call_args.kwargs
    assert kwargs["interaction_id"] == interaction_id
    assert kwargs["attendees"] == [
        (None, attendee_contact_id, CrmAttendeeRole.ATTENDEE)
    ]


def test_patch_interaction_not_found() -> None:
    not_found = OnyxError(OnyxErrorCode.NOT_FOUND, "CRM interaction not found.")

    with patch(
        "onyx.server.features.crm.api._load_interaction_or_404",
        side_effect=not_found,
    ):
        with pytest.raises(OnyxError) as exc:
            patch_interaction(
                interaction_id=uuid4(),
                interaction_patch_request=CrmInteractionPatchRequest(title="x"),
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.status_code == 404


def test_serialize_interaction_includes_attendee_display_names() -> None:
    now = datetime.now(timezone.utc)
    interaction_id = uuid4()
    interaction_contact_id = uuid4()
    interaction_organization_id = uuid4()
    attendee_user_id = uuid4()
    attendee_contact_id = uuid4()

    interaction = SimpleNamespace(
        id=interaction_id,
        contact_id=interaction_contact_id,
        organization_id=interaction_organization_id,
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
    interaction_contact_model = SimpleNamespace(
        first_name="Taylor",
        last_name="Jones",
        email="taylor@example.com",
    )
    interaction_organization_model = SimpleNamespace(name="Acme Corp")
    db_session = MagicMock()

    def _mock_get(_model, id):  # noqa: ANN001, ANN202
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
            side_effect=lambda contact_id, _db_session: (
                attendee_contact_model
                if contact_id == attendee_contact_id
                else interaction_contact_model
                if contact_id == interaction_contact_id
                else None
            ),
        ),
        patch(
            "onyx.server.features.crm.api.get_organization_by_id",
            return_value=interaction_organization_model,
        ),
    ):
        serialized = _serialize_interaction(interaction, db_session)

    assert [a.display_name for a in serialized.attendees] == ["Alex Smith", "Sam Lee"]
    assert serialized.contact_name == "Taylor Jones"
    assert serialized.organization_name == "Acme Corp"


# ---------------------------------------------------------------------------
# Date-range filters + sort direction (REST layer)
# ---------------------------------------------------------------------------


def test_get_contacts_passes_date_filters_through() -> None:
    with (
        patch(
            "onyx.server.features.crm.api.list_contacts",
            return_value=([], 0),
        ) as mock_list_contacts,
        patch(
            "onyx.server.features.crm.api._serialize_contact",
            return_value={},
        ),
    ):
        get_contacts(
            status=None,
            category=None,
            sort_by=None,
            sort_dir=None,
            created_after="2026-01-01T00:00:00Z",
            created_before=None,
            updated_after=None,
            updated_before="2026-02-01T12:30:00Z",
            db_session=MagicMock(),
            _user=SimpleNamespace(id=uuid4()),
        )

    kwargs = mock_list_contacts.call_args.kwargs
    assert isinstance(kwargs["created_after"], datetime)
    assert kwargs["created_after"].tzinfo is not None
    assert kwargs["created_after"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert kwargs["updated_before"] == datetime(
        2026, 2, 1, 12, 30, tzinfo=timezone.utc
    )
    assert kwargs["created_before"] is None
    assert kwargs["updated_after"] is None


def test_get_contacts_rejects_malformed_date() -> None:
    with patch(
        "onyx.server.features.crm.api.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        with pytest.raises(OnyxError) as exc:
            get_contacts(
                status=None,
                category=None,
                sort_by=None,
                sort_dir=None,
                created_after="not-a-date",
                created_before=None,
                updated_after=None,
                updated_before=None,
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    assert exc.value.status_code == 400
    mock_list_contacts.assert_not_called()


def test_get_contacts_rejects_invalid_sort_dir() -> None:
    with patch(
        "onyx.server.features.crm.api.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        with pytest.raises(OnyxError) as exc:
            get_contacts(
                status=None,
                category=None,
                sort_by=None,
                sort_dir="sideways",
                created_after=None,
                created_before=None,
                updated_after=None,
                updated_before=None,
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    mock_list_contacts.assert_not_called()


def test_get_contacts_accepts_sort_dir_asc() -> None:
    with (
        patch(
            "onyx.server.features.crm.api.list_contacts",
            return_value=([], 0),
        ) as mock_list_contacts,
        patch("onyx.server.features.crm.api._serialize_contact", return_value={}),
    ):
        get_contacts(
            status=None,
            category=None,
            sort_by=None,
            sort_dir="ASC",
            created_after=None,
            created_before=None,
            updated_after=None,
            updated_before=None,
            db_session=MagicMock(),
            _user=SimpleNamespace(id=uuid4()),
        )

    assert mock_list_contacts.call_args.kwargs["sort_dir"] == "asc"


def test_get_contacts_rejects_invalid_sort_by() -> None:
    with patch(
        "onyx.server.features.crm.api.list_contacts",
        return_value=([], 0),
    ) as mock_list_contacts:
        with pytest.raises(OnyxError) as exc:
            get_contacts(
                status=None,
                category=None,
                sort_by="bogus",
                sort_dir=None,
                created_after=None,
                created_before=None,
                updated_after=None,
                updated_before=None,
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    mock_list_contacts.assert_not_called()


def test_get_contacts_bare_date_before_extends_to_end_of_day() -> None:
    with (
        patch(
            "onyx.server.features.crm.api.list_contacts",
            return_value=([], 0),
        ) as mock_list_contacts,
        patch("onyx.server.features.crm.api._serialize_contact", return_value={}),
    ):
        get_contacts(
            status=None,
            category=None,
            sort_by=None,
            sort_dir=None,
            created_after=None,
            created_before="2026-01-31",
            updated_after=None,
            updated_before=None,
            db_session=MagicMock(),
            _user=SimpleNamespace(id=uuid4()),
        )

    kwargs = mock_list_contacts.call_args.kwargs
    assert kwargs["created_before"] == datetime(
        2026, 1, 31, 23, 59, 59, 999999, tzinfo=timezone.utc
    )


def test_get_contacts_explicit_midnight_before_not_extended() -> None:
    with (
        patch(
            "onyx.server.features.crm.api.list_contacts",
            return_value=([], 0),
        ) as mock_list_contacts,
        patch("onyx.server.features.crm.api._serialize_contact", return_value={}),
    ):
        get_contacts(
            status=None,
            category=None,
            sort_by=None,
            sort_dir=None,
            created_after=None,
            created_before="2026-01-31T00:00:00Z",
            updated_after=None,
            updated_before=None,
            db_session=MagicMock(),
            _user=SimpleNamespace(id=uuid4()),
        )

    kwargs = mock_list_contacts.call_args.kwargs
    assert kwargs["created_before"] == datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc)


def test_get_contacts_empty_when_after_greater_than_before() -> None:
    with (
        patch(
            "onyx.server.features.crm.api.list_contacts",
            return_value=([], 0),
        ) as mock_list_contacts,
        patch("onyx.server.features.crm.api._serialize_contact", return_value={}),
    ):
        get_contacts(
            status=None,
            category=None,
            sort_by=None,
            sort_dir=None,
            created_after="2026-06-01T00:00:00Z",
            created_before="2026-01-01T00:00:00Z",
            updated_after=None,
            updated_before=None,
            db_session=MagicMock(),
            _user=SimpleNamespace(id=uuid4()),
        )

    # Inverted range is passed through without error (documents non-error contract).
    kwargs = mock_list_contacts.call_args.kwargs
    assert kwargs["created_after"] == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert kwargs["created_before"] == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_get_organizations_passes_date_filters_through() -> None:
    with (
        patch(
            "onyx.server.features.crm.api.list_organizations",
            return_value=([], 0),
        ) as mock_list_organizations,
        patch(
            "onyx.server.features.crm.api._serialize_organization",
            return_value={},
        ),
    ):
        get_organizations(
            sort_by=None,
            sort_dir="asc",
            created_after="2026-01-01T00:00:00Z",
            created_before=None,
            updated_after=None,
            updated_before=None,
            db_session=MagicMock(),
            _user=SimpleNamespace(id=uuid4()),
        )

    kwargs = mock_list_organizations.call_args.kwargs
    assert kwargs["created_after"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert kwargs["sort_dir"] == "asc"


def test_get_organizations_rejects_malformed_date() -> None:
    with patch(
        "onyx.server.features.crm.api.list_organizations",
        return_value=([], 0),
    ) as mock_list_organizations:
        with pytest.raises(OnyxError) as exc:
            get_organizations(
                sort_by=None,
                sort_dir=None,
                created_after=None,
                created_before=None,
                updated_after="garbage",
                updated_before=None,
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    mock_list_organizations.assert_not_called()


def test_get_organizations_rejects_invalid_sort_dir() -> None:
    with patch(
        "onyx.server.features.crm.api.list_organizations",
        return_value=([], 0),
    ) as mock_list_organizations:
        with pytest.raises(OnyxError) as exc:
            get_organizations(
                sort_by=None,
                sort_dir="up",
                created_after=None,
                created_before=None,
                updated_after=None,
                updated_before=None,
                db_session=MagicMock(),
                _user=SimpleNamespace(id=uuid4()),
            )

    assert exc.value.error_code == OnyxErrorCode.VALIDATION_ERROR
    mock_list_organizations.assert_not_called()


_CONTACT_IMPORT_BASE_HEADERS = [
    "first_name",
    "last_name",
    "email",
    "phone",
    "title",
    "organization_name",
    "owner_emails",
    "source",
    "status",
    "category",
    "notes",
    "linkedin_url",
    "location",
    "tags",
]


def _run_contact_import(
    csv_text: str,
    contact_email_lookup: dict[str, object] | None = None,
) -> tuple[object, MagicMock, MagicMock]:
    file = MagicMock()
    file.read = AsyncMock(return_value=csv_text.encode("utf-8"))
    db_session = MagicMock()
    created_contact = SimpleNamespace(id=uuid4())
    existing_contact = SimpleNamespace(id=uuid4())

    with (
        patch("onyx.server.features.crm.api.build_org_name_lookup", return_value={}),
        patch(
            "onyx.server.features.crm.api.build_contact_email_lookup",
            return_value=contact_email_lookup or {},
        ),
        patch(
            "onyx.server.features.crm.api.build_user_email_lookup", return_value={}
        ),
        patch(
            "onyx.server.features.crm.api.get_allowed_contact_stages",
            return_value=["lead"],
        ),
        patch(
            "onyx.server.features.crm.api.create_contact",
            return_value=(created_contact, True),
        ) as mock_create_contact,
        patch(
            "onyx.server.features.crm.api.update_contact",
            return_value=(existing_contact, True),
        ) as mock_update_contact,
        patch("onyx.server.features.crm.api.get_contact_tags", return_value=[]),
    ):
        result = asyncio.run(
            import_contacts_csv(
                file=file,
                dry_run=False,
                user=SimpleNamespace(id=uuid4()),
                db_session=db_session,
            )
        )

    return result, mock_create_contact, mock_update_contact


def test_import_contacts_parses_policy_fields() -> None:
    headers = _CONTACT_IMPORT_BASE_HEADERS + [
        "party_affiliation",
        "us_state",
        "principal",
    ]
    csv_text = (
        ",".join(headers)
        + "\n"
        + "Alice,Smith,,,,,,,,,,,,,Democrat,ca,Senator Doe\n"
    )

    result, mock_create_contact, _ = _run_contact_import(csv_text)

    assert result.created == 1
    assert result.errors == []
    kwargs = mock_create_contact.call_args.kwargs
    assert kwargs["party_affiliation"] == "Democrat"
    assert kwargs["us_state"] == "ca"
    assert kwargs["principal"] == "Senator Doe"


def test_import_contacts_without_policy_columns_still_succeeds() -> None:
    csv_text = (
        ",".join(_CONTACT_IMPORT_BASE_HEADERS)
        + "\n"
        + "Alice,Smith,,,,,,,,,,,,\n"
    )

    result, mock_create_contact, _ = _run_contact_import(csv_text)

    assert result.created == 1
    assert result.errors == []
    kwargs = mock_create_contact.call_args.kwargs
    assert kwargs["party_affiliation"] is None
    assert kwargs["us_state"] is None
    assert kwargs["principal"] is None


def _contact_import_row(headers: list[str], **values: str) -> str:
    row = {h: "" for h in headers}
    row.update(values)
    return ",".join(row[h] for h in headers)


def test_import_contacts_old_format_preserves_policy_fields_on_update() -> None:
    existing_id = uuid4()
    headers = _CONTACT_IMPORT_BASE_HEADERS
    csv_text = (
        ",".join(headers)
        + "\n"
        + _contact_import_row(
            headers,
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
        )
        + "\n"
    )

    result, _, mock_update_contact = _run_contact_import(
        csv_text,
        contact_email_lookup={"alice@example.com": existing_id},
    )

    assert result.updated == 1
    assert result.errors == []
    patches = mock_update_contact.call_args.kwargs["patches"]
    assert "party_affiliation" not in patches
    assert "us_state" not in patches
    assert "principal" not in patches


def test_import_contacts_with_empty_policy_columns_clears_on_update() -> None:
    existing_id = uuid4()
    headers = _CONTACT_IMPORT_BASE_HEADERS + [
        "party_affiliation",
        "us_state",
        "principal",
    ]
    csv_text = (
        ",".join(headers)
        + "\n"
        + _contact_import_row(
            headers,
            first_name="Alice",
            last_name="Smith",
            email="alice@example.com",
        )
        + "\n"
    )

    result, _, mock_update_contact = _run_contact_import(
        csv_text,
        contact_email_lookup={"alice@example.com": existing_id},
    )

    assert result.updated == 1
    assert result.errors == []
    patches = mock_update_contact.call_args.kwargs["patches"]
    assert patches["party_affiliation"] is None
    assert patches["us_state"] is None
    assert patches["principal"] is None
