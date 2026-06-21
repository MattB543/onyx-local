from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.db.crm import _build_timestamp_order_clauses
from onyx.db.crm import build_contact_email_lookup
from onyx.db.crm import build_org_name_lookup
from onyx.db.crm import create_contact
from onyx.db.crm import create_interaction
from onyx.db.crm import create_organization
from onyx.db.crm import create_tag
from onyx.db.crm import delete_contact
from onyx.db.crm import delete_interaction
from onyx.db.crm import delete_organization
from onyx.db.crm import export_all_contacts
from onyx.db.crm import find_contacts_for_attendee_resolution
from onyx.db.crm import find_users_for_attendee_resolution
from onyx.db.crm import get_contact_by_email
from onyx.db.crm import get_organization_by_name
from onyx.db.crm import list_contacts
from onyx.db.crm import list_organizations
from onyx.db.crm import list_tags
from onyx.db.crm import replace_interaction_attendees
from onyx.db.crm import search_crm_entities
from onyx.db.crm import update_contact
from onyx.db.crm import update_interaction
from onyx.db.crm import update_organization
from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmInteractionType
from onyx.db.models import CrmContact
from onyx.db.models import CrmInteraction
from onyx.db.models import CrmInteractionAttendee
from onyx.db.models import CrmOrganization


def test_search_crm_entities_returns_empty_for_blank_query() -> None:
    db_session = MagicMock()

    results, total = search_crm_entities(
        db_session=db_session,
        query="   ",
        entity_types=None,
        page_num=0,
        page_size=25,
    )

    assert results == []
    assert total == 0
    db_session.execute.assert_not_called()


def test_search_crm_entities_returns_result_rows() -> None:
    db_session = MagicMock()
    now = datetime(2026, 2, 16, tzinfo=timezone.utc)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    rows_result = MagicMock()
    rows_result.mappings.return_value = [
        {
            "entity_type": "contact",
            "entity_id": str(uuid4()),
            "primary_text": "Alice Smith",
            "secondary_text": "alice@example.com",
            "sort_at": now,
            "rank": 0.92,
        },
        {
            "entity_type": "organization",
            "entity_id": str(uuid4()),
            "primary_text": "Acme Corp",
            "secondary_text": None,
            "sort_at": now,
            "rank": 0.75,
        },
    ]
    db_session.execute.side_effect = [count_result, rows_result]

    results, total = search_crm_entities(
        db_session=db_session,
        query="alice",
        entity_types=None,
        page_num=0,
        page_size=25,
    )

    assert total == 2
    assert len(results) == 2
    assert results[0].entity_type == "contact"
    assert results[0].primary_text == "Alice Smith"
    assert results[0].secondary_text == "alice@example.com"
    assert results[1].entity_type == "organization"
    assert results[1].primary_text == "Acme Corp"


def test_create_contact_happy_path_creates_contact() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None

    contact, created = create_contact(
        db_session=db_session,
        first_name="  Alice ",
        last_name=" Smith ",
        email=" Alice@Example.com ",
        phone=" 123 ",
        title=" VP ",
        organization_id=None,
        source=None,
        status="lead",
        notes=" Important lead ",
        linkedin_url=" https://linkedin.com/in/alice ",
        location=" NY ",
        created_by=uuid4(),
    )

    assert created is True
    assert contact.first_name == "Alice"
    assert contact.last_name == "Smith"
    assert contact.email == "alice@example.com"
    assert contact.notes == "Important lead"
    db_session.add.assert_called_once_with(contact)
    db_session.commit.assert_called_once()
    db_session.refresh.assert_called_once_with(contact)


def test_create_contact_last_name_only_succeeds() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None

    contact, created = create_contact(
        db_session=db_session,
        first_name=None,
        last_name=" Smith ",
        email=None,
        phone=None,
        title=None,
        organization_id=None,
        source=None,
        status="lead",
        notes=None,
        linkedin_url=None,
        location=None,
        created_by=uuid4(),
    )

    assert created is True
    assert contact.first_name is None
    assert contact.last_name == "Smith"


def test_create_contact_rejects_no_names() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None

    with pytest.raises(
        ValueError, match="at least a first name or a last name"
    ):
        create_contact(
            db_session=db_session,
            first_name="   ",
            last_name=None,
            email="someone@example.com",
            phone=None,
            title=None,
            organization_id=None,
            source=None,
            status="lead",
            notes=None,
            linkedin_url=None,
            location=None,
            created_by=uuid4(),
        )


def test_update_contact_can_clear_first_name_when_last_name_present() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None
    contact = CrmContact(first_name="Alice", last_name="Smith", status="lead")
    contact.id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={"first_name": ""},
    )

    assert updated is contact
    assert changed is True
    assert contact.first_name is None
    assert contact.last_name == "Smith"


def test_update_contact_rejects_clearing_only_first_name() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None
    contact = CrmContact(first_name="Alice", last_name=None, status="lead")
    contact.id = uuid4()

    with pytest.raises(
        ValueError, match="at least a first name or a last name"
    ):
        update_contact(
            db_session=db_session,
            contact=contact,
            patches={"first_name": "  "},
        )


@pytest.mark.parametrize(
    "patches",
    [
        {"first_name": "", "last_name": ""},
        {"last_name": "", "first_name": ""},
    ],
)
def test_update_contact_rejects_clearing_both_names_in_one_patch(
    patches: dict[str, str],
) -> None:
    # The invariant must hold regardless of dict iteration order, so both
    # orderings of a single both-names-cleared patch are rejected.
    db_session = MagicMock()
    db_session.scalar.return_value = None
    contact = CrmContact(first_name="Alice", last_name="Smith", status="lead")
    contact.id = uuid4()

    with pytest.raises(
        ValueError, match="at least a first name or a last name"
    ):
        update_contact(
            db_session=db_session,
            contact=contact,
            patches=patches,
        )


def test_update_contact_rejects_clearing_last_when_no_first() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None
    contact = CrmContact(first_name=None, last_name="Smith", status="lead")
    contact.id = uuid4()

    with pytest.raises(
        ValueError, match="at least a first name or a last name"
    ):
        update_contact(
            db_session=db_session,
            contact=contact,
            patches={"last_name": ""},
        )


def test_get_contact_by_email_normalizes_case() -> None:
    db_session = MagicMock()
    expected_contact = MagicMock()
    db_session.scalar.return_value = expected_contact

    result = get_contact_by_email("  TEST@EXAMPLE.COM ", db_session)

    assert result is expected_contact
    db_session.scalar.assert_called_once()


def test_update_contact_happy_path_ignores_protected_fields() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None
    contact = CrmContact(first_name="Alice", status="lead")
    contact.id = uuid4()
    original_created_at = contact.created_at

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={
            "first_name": "  Alicia ",
            "email": "Alicia@example.com",
            "notes": " updated ",
            "id": uuid4(),
            "created_at": "should_be_ignored",
        },
    )

    assert updated is contact
    assert changed is True
    assert contact.first_name == "Alicia"
    assert contact.email == "alicia@example.com"
    assert contact.notes == "updated"
    assert contact.created_at == original_created_at
    db_session.commit.assert_called_once()
    db_session.refresh.assert_called_once_with(contact)


def test_update_contact_rejects_duplicate_email() -> None:
    db_session = MagicMock()
    contact = CrmContact(first_name="Alice", status="lead")
    contact.id = uuid4()
    existing_contact = CrmContact(first_name="Bob", status="lead")
    existing_contact.id = uuid4()
    db_session.scalar.return_value = existing_contact

    with pytest.raises(ValueError, match="already exists"):
        update_contact(
            db_session=db_session,
            contact=contact,
            patches={"email": "shared@example.com"},
        )

    db_session.commit.assert_not_called()


def test_update_contact_semantically_identical_values_do_not_mark_changed() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None
    contact = CrmContact(
        first_name=" Alice ",
        last_name="Smith ",
        email="Alice@Example.com",
        phone="",
        title=" VP ",
        status="Lead",
        category="",
        notes=" Important lead ",
        linkedin_url="",
        location=" NY ",
    )
    contact.id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={
            "first_name": "Alice",
            "last_name": "Smith",
            "email": "Alice@Example.com",
            "phone": None,
            "title": "VP",
            "status": "Lead",
            "category": None,
            "notes": "Important lead",
            "linkedin_url": None,
            "location": "NY",
        },
        commit=False,
    )

    assert updated is contact
    assert changed is False
    db_session.flush.assert_not_called()
    db_session.commit.assert_not_called()
    db_session.refresh.assert_not_called()


def test_update_contact_sets_profile_picture_file_id() -> None:
    db_session = MagicMock()
    contact = CrmContact(first_name="Alice", status="lead")
    contact.id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": "file-123"},
        commit=False,
    )

    assert updated is contact
    assert changed is True
    assert contact.profile_picture_file_id == "file-123"
    db_session.flush.assert_called_once()
    db_session.refresh.assert_called_once_with(contact)


def test_update_contact_sets_organization_id() -> None:
    db_session = MagicMock()
    contact = CrmContact(first_name="Alice", status="lead")
    contact.id = uuid4()
    organization_id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={"organization_id": organization_id},
        commit=False,
    )

    assert updated is contact
    assert changed is True
    assert contact.organization_id == organization_id
    db_session.flush.assert_called_once()
    db_session.refresh.assert_called_once_with(contact)


def test_update_contact_clears_organization_id() -> None:
    db_session = MagicMock()
    contact = CrmContact(
        first_name="Alice",
        status="lead",
        organization_id=uuid4(),
    )
    contact.id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={"organization_id": None},
        commit=False,
    )

    assert updated is contact
    assert changed is True
    assert contact.organization_id is None
    db_session.flush.assert_called_once()
    db_session.refresh.assert_called_once_with(contact)


def test_update_contact_organization_id_noop_does_not_mark_changed() -> None:
    db_session = MagicMock()
    organization_id = uuid4()
    contact = CrmContact(
        first_name="Alice",
        status="lead",
        organization_id=organization_id,
    )
    contact.id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={"organization_id": organization_id},
        commit=False,
    )

    assert updated is contact
    assert changed is False
    db_session.flush.assert_not_called()
    db_session.refresh.assert_not_called()


def test_update_contact_clears_profile_picture_file_id() -> None:
    db_session = MagicMock()
    contact = CrmContact(
        first_name="Alice",
        status="lead",
        profile_picture_file_id="file-123",
    )
    contact.id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": None},
        commit=False,
    )

    assert updated is contact
    assert changed is True
    assert contact.profile_picture_file_id is None
    db_session.flush.assert_called_once()
    db_session.refresh.assert_called_once_with(contact)


def test_update_contact_profile_picture_noop_does_not_mark_changed() -> None:
    db_session = MagicMock()
    contact = CrmContact(
        first_name="Alice",
        status="lead",
        profile_picture_file_id="file-123",
    )
    contact.id = uuid4()

    updated, changed = update_contact(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": "file-123"},
        commit=False,
    )

    assert updated is contact
    assert changed is False
    db_session.flush.assert_not_called()
    db_session.refresh.assert_not_called()


def test_export_all_contacts_empty_profile_picture_url() -> None:
    db_session = MagicMock()
    contact = CrmContact(
        first_name="Bob",
        status="lead",
    )
    contact.id = uuid4()
    db_session.scalars.return_value = [contact]

    owner_rows = MagicMock()
    owner_rows.all.return_value = []
    tag_rows = MagicMock()
    tag_rows.all.return_value = []
    db_session.execute.side_effect = [owner_rows, tag_rows]

    rows = export_all_contacts(db_session)

    assert rows[0]["profile_picture_url"] == ""


def test_export_all_contacts_includes_profile_picture_url() -> None:
    db_session = MagicMock()
    contact = CrmContact(
        first_name="Alice",
        status="lead",
        profile_picture_file_id="file-123",
    )
    contact.id = uuid4()
    db_session.scalars.return_value = [contact]

    owner_rows = MagicMock()
    owner_rows.all.return_value = []
    tag_rows = MagicMock()
    tag_rows.all.return_value = []
    db_session.execute.side_effect = [owner_rows, tag_rows]

    rows = export_all_contacts(db_session)

    assert rows[0]["profile_picture_url"] == "/api/chat/file/file-123"


def test_create_organization_rejects_empty_name() -> None:
    db_session = MagicMock()

    with pytest.raises(ValueError, match="Organization name cannot be empty"):
        create_organization(
            db_session=db_session,
            name="   ",
            website=None,
            type=None,
            sector=None,
            location=None,
            size=None,
            notes=None,
            created_by=uuid4(),
        )

    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_create_organization_happy_path_creates_org() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None

    organization, created = create_organization(
        db_session=db_session,
        name="  Acme Inc ",
        website=" https://acme.com ",
        type=None,
        sector=" SaaS ",
        location=" Remote ",
        size=" 50-100 ",
        notes=" strategic ",
        created_by=uuid4(),
    )

    assert created is True
    assert organization.name == "Acme Inc"
    assert organization.website == "https://acme.com"
    assert organization.notes == "strategic"
    db_session.add.assert_called_once_with(organization)
    db_session.commit.assert_called_once()
    db_session.refresh.assert_called_once_with(organization)


def test_get_organization_by_name_normalizes_input() -> None:
    db_session = MagicMock()
    expected_organization = MagicMock()
    db_session.scalar.return_value = expected_organization

    result = get_organization_by_name("  AcMe  ", db_session)

    assert result is expected_organization
    db_session.scalar.assert_called_once()


def test_update_organization_happy_path_normalizes_name() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = None
    organization = CrmOrganization(name="Old Name")
    organization.id = uuid4()

    updated, changed = update_organization(
        db_session=db_session,
        organization=organization,
        patches={"name": "  New Name  ", "notes": "  Updated notes  "},
    )

    assert updated is organization
    assert changed is True
    assert organization.name == "New Name"
    assert organization.notes == "Updated notes"
    db_session.commit.assert_called_once()
    db_session.refresh.assert_called_once_with(organization)


def test_update_organization_rejects_duplicate_name() -> None:
    db_session = MagicMock()
    organization = CrmOrganization(name="Acme")
    organization.id = uuid4()
    existing = CrmOrganization(name="Acme")
    existing.id = uuid4()
    db_session.scalar.return_value = existing

    with pytest.raises(ValueError, match="already exists"):
        update_organization(
            db_session=db_session,
            organization=organization,
            patches={"name": "Acme"},
        )

    db_session.commit.assert_not_called()


def test_update_organization_semantically_identical_values_do_not_mark_changed() -> (
    None
):
    db_session = MagicMock()
    db_session.scalar.return_value = None
    organization = CrmOrganization(
        name=" Acme ",
        website=" ACME.COM ",
        sector="",
        location=" Remote ",
        size="",
        notes=" Strategic ",
    )
    organization.id = uuid4()

    updated, changed = update_organization(
        db_session=db_session,
        organization=organization,
        patches={
            "name": "Acme",
            "website": "ACME.COM",
            "sector": None,
            "location": "Remote",
            "size": None,
            "notes": "Strategic",
        },
        commit=False,
    )

    assert updated is organization
    assert changed is False
    db_session.flush.assert_not_called()
    db_session.commit.assert_not_called()
    db_session.refresh.assert_not_called()


def test_delete_contact_commits_by_default() -> None:
    db_session = MagicMock()
    contact = CrmContact(first_name="Alice", status="lead")

    delete_contact(db_session=db_session, contact=contact)

    db_session.delete.assert_called_once_with(contact)
    db_session.commit.assert_called_once()
    db_session.flush.assert_not_called()


def test_delete_contact_flushes_without_commit_when_requested() -> None:
    db_session = MagicMock()
    contact = CrmContact(first_name="Alice", status="lead")

    delete_contact(db_session=db_session, contact=contact, commit=False)

    db_session.delete.assert_called_once_with(contact)
    db_session.flush.assert_called_once()
    db_session.commit.assert_not_called()


def test_delete_organization_commits_by_default() -> None:
    db_session = MagicMock()
    organization = CrmOrganization(name="Acme")

    delete_organization(db_session=db_session, organization=organization)

    db_session.delete.assert_called_once_with(organization)
    db_session.commit.assert_called_once()
    db_session.flush.assert_not_called()


def test_delete_organization_flushes_without_commit_when_requested() -> None:
    db_session = MagicMock()
    organization = CrmOrganization(name="Acme")

    delete_organization(
        db_session=db_session,
        organization=organization,
        commit=False,
    )

    db_session.delete.assert_called_once_with(organization)
    db_session.flush.assert_called_once()
    db_session.commit.assert_not_called()


def test_create_interaction_does_not_auto_add_primary_contact_attendee() -> None:
    db_session = MagicMock()
    contact_id = uuid4()

    with patch("onyx.db.crm.add_interaction_attendees") as mock_add_attendees:
        interaction = create_interaction(
            db_session=db_session,
            contact_id=contact_id,
            organization_id=None,
            logged_by=uuid4(),
            interaction_type=CrmInteractionType.NOTE,
            title="  Intro Call ",
            summary="  Follow-up next week ",
            occurred_at=None,
        )

    assert interaction.title == "Intro Call"
    assert interaction.summary == "Follow-up next week"
    db_session.add.assert_called_once_with(interaction)
    db_session.commit.assert_called_once()
    db_session.refresh.assert_called_once_with(interaction)
    mock_add_attendees.assert_not_called()


def test_update_interaction_updates_title_and_summary() -> None:
    db_session = MagicMock()
    interaction = CrmInteraction(
        type=CrmInteractionType.NOTE,
        title="Old title",
        summary="Old summary",
    )
    interaction.id = uuid4()

    updated, changed = update_interaction(
        db_session=db_session,
        interaction=interaction,
        patches={"title": "  New title ", "summary": "  New summary "},
    )

    assert updated is interaction
    assert changed is True
    assert interaction.title == "New title"
    assert interaction.summary == "New summary"
    db_session.commit.assert_called_once()
    db_session.refresh.assert_called_once_with(interaction)


def test_update_interaction_noop_does_not_mark_changed() -> None:
    db_session = MagicMock()
    interaction = CrmInteraction(
        type=CrmInteractionType.NOTE,
        title=" Intro ",
        summary=" Summary ",
    )
    interaction.id = uuid4()

    updated, changed = update_interaction(
        db_session=db_session,
        interaction=interaction,
        patches={"title": "Intro", "summary": "Summary"},
        commit=False,
    )

    assert updated is interaction
    assert changed is False
    db_session.flush.assert_not_called()
    db_session.commit.assert_not_called()
    db_session.refresh.assert_not_called()


def test_update_interaction_rejects_empty_title() -> None:
    db_session = MagicMock()
    interaction = CrmInteraction(
        type=CrmInteractionType.NOTE,
        title="Has title",
        summary=None,
    )
    interaction.id = uuid4()

    with pytest.raises(ValueError, match="title cannot be empty"):
        update_interaction(
            db_session=db_session,
            interaction=interaction,
            patches={"title": "   "},
        )

    db_session.commit.assert_not_called()


def test_update_interaction_sets_and_clears_occurred_at() -> None:
    db_session = MagicMock()
    interaction = CrmInteraction(
        type=CrmInteractionType.NOTE,
        title="Has title",
        summary=None,
    )
    interaction.id = uuid4()
    interaction.occurred_at = None

    occurred_at = datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
    _, changed = update_interaction(
        db_session=db_session,
        interaction=interaction,
        patches={"occurred_at": occurred_at},
    )
    assert changed is True
    assert interaction.occurred_at == occurred_at

    db_session.reset_mock()
    _, changed = update_interaction(
        db_session=db_session,
        interaction=interaction,
        patches={"occurred_at": None},
    )
    assert changed is True
    assert interaction.occurred_at is None
    db_session.commit.assert_called_once()


def test_update_interaction_changes_type() -> None:
    db_session = MagicMock()
    interaction = CrmInteraction(
        type=CrmInteractionType.NOTE,
        title="Has title",
        summary=None,
    )
    interaction.id = uuid4()

    _, changed = update_interaction(
        db_session=db_session,
        interaction=interaction,
        patches={"type": CrmInteractionType.CALL},
    )

    assert changed is True
    assert interaction.type == CrmInteractionType.CALL


def test_replace_interaction_attendees_replaces_set() -> None:
    db_session = MagicMock()
    interaction_id = uuid4()
    user_id = uuid4()
    contact_id = uuid4()

    final_attendees = [MagicMock(), MagicMock()]
    db_session.scalars.return_value = final_attendees

    result = replace_interaction_attendees(
        db_session=db_session,
        interaction_id=interaction_id,
        attendees=[
            (user_id, None, CrmAttendeeRole.ATTENDEE),
            (user_id, None, CrmAttendeeRole.ORGANIZER),
            (None, contact_id, CrmAttendeeRole.ATTENDEE),
        ],
    )

    # delete existing + add deduped rows
    db_session.execute.assert_called_once()
    added = [call.args[0] for call in db_session.add.call_args_list]
    assert len(added) == 2
    by_pair = {(a.user_id, a.contact_id): a for a in added}
    assert by_pair[(user_id, None)].role == CrmAttendeeRole.ORGANIZER
    assert by_pair[(None, contact_id)].role == CrmAttendeeRole.ATTENDEE
    assert all(isinstance(a, CrmInteractionAttendee) for a in added)
    db_session.commit.assert_called_once()
    assert result == final_attendees


def test_replace_interaction_attendees_empty_clears_all() -> None:
    db_session = MagicMock()
    db_session.scalars.return_value = []

    result = replace_interaction_attendees(
        db_session=db_session,
        interaction_id=uuid4(),
        attendees=[],
    )

    db_session.execute.assert_called_once()
    db_session.add.assert_not_called()
    db_session.commit.assert_called_once()
    assert result == []


def test_delete_interaction_commits_by_default() -> None:
    db_session = MagicMock()
    interaction = MagicMock()

    delete_interaction(db_session=db_session, interaction=interaction)

    db_session.delete.assert_called_once_with(interaction)
    db_session.commit.assert_called_once()
    db_session.flush.assert_not_called()


def test_delete_interaction_flushes_without_commit_when_requested() -> None:
    db_session = MagicMock()
    interaction = MagicMock()

    delete_interaction(db_session=db_session, interaction=interaction, commit=False)

    db_session.delete.assert_called_once_with(interaction)
    db_session.flush.assert_called_once()
    db_session.commit.assert_not_called()


def test_create_tag_rejects_empty_name() -> None:
    db_session = MagicMock()

    with pytest.raises(ValueError, match="Tag name cannot be empty"):
        create_tag(
            db_session=db_session,
            name="",
            color=None,
        )

    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_find_contacts_for_attendee_resolution_returns_empty_on_blank_token() -> None:
    db_session = MagicMock()

    contacts = find_contacts_for_attendee_resolution(
        db_session=db_session,
        token="   ",
    )

    assert contacts == []
    db_session.scalars.assert_not_called()


def test_list_contacts_escapes_like_metacharacters() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = 0
    db_session.scalars.return_value = []
    query = "ali_ce%corp"
    expected_like = "%ali\\_ce\\%corp%"

    list_contacts(
        db_session=db_session,
        page_num=0,
        page_size=10,
        query=query,
    )

    stmt = db_session.scalars.call_args.args[0]
    compiled = stmt.compile()
    assert expected_like in compiled.params.values()


def test_list_organizations_escapes_like_metacharacters() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = 0
    db_session.scalars.return_value = []
    query = "ac_me%inc"
    expected_like = "%ac\\_me\\%inc%"

    list_organizations(
        db_session=db_session,
        page_num=0,
        page_size=10,
        query=query,
    )

    stmt = db_session.scalars.call_args.args[0]
    compiled = stmt.compile()
    assert expected_like in compiled.params.values()


def test_build_contact_email_lookup_normalizes_keys() -> None:
    db_session = MagicMock()
    db_session.execute.return_value.all.return_value = [
        (uuid4(), " Alice@Example.com "),
        (uuid4(), ""),
    ]

    lookup = build_contact_email_lookup(db_session)

    assert list(lookup.keys()) == ["alice@example.com"]


def test_build_org_name_lookup_normalizes_keys() -> None:
    db_session = MagicMock()
    org_id = uuid4()
    db_session.execute.return_value.all.return_value = [
        (org_id, " Acme Corp "),
        (uuid4(), ""),
    ]

    lookup = build_org_name_lookup(db_session)

    assert lookup == {"acme corp": org_id}


def test_list_tags_escapes_like_metacharacters() -> None:
    db_session = MagicMock()
    db_session.scalar.return_value = 0
    db_session.scalars.return_value = []
    query = "vip_%tag"
    expected_like = "%vip\\_\\%tag%"

    list_tags(
        db_session=db_session,
        page_num=0,
        page_size=10,
        query=query,
    )

    stmt = db_session.scalars.call_args.args[0]
    compiled = stmt.compile()
    assert expected_like in compiled.params.values()


def test_find_contacts_for_attendee_resolution_returns_matches() -> None:
    db_session = MagicMock()
    contact = CrmContact(
        first_name="Alice",
        last_name="Smith",
        email="alice@example.com",
        status="lead",
    )
    contact.id = uuid4()
    db_session.scalars.return_value = [contact]
    token = "ali_ce%corp"
    expected_like = "%ali\\_ce\\%corp%"

    contacts = find_contacts_for_attendee_resolution(
        db_session=db_session,
        token=token,
        max_results=5,
    )

    assert contacts == [contact]
    stmt = db_session.scalars.call_args.args[0]
    compiled = stmt.compile()
    assert expected_like in compiled.params.values()


def test_find_users_for_attendee_resolution_returns_empty_on_blank_token() -> None:
    db_session = MagicMock()

    users = find_users_for_attendee_resolution(
        db_session=db_session,
        token="",
    )

    assert users == []
    db_session.scalars.assert_not_called()


def test_find_users_for_attendee_resolution_returns_matches() -> None:
    db_session = MagicMock()
    user = MagicMock()
    user.id = uuid4()
    user.email = "alice@example.com"
    user.personal_name = "Alice Smith"
    scalars_result = MagicMock()
    scalars_result.unique.return_value = [user]
    db_session.scalars.return_value = scalars_result
    token = "ali_ce%"
    expected_like = "%ali\\_ce\\%%"

    users = find_users_for_attendee_resolution(
        db_session=db_session,
        token=token,
        max_results=5,
    )

    assert users == [user]
    stmt = db_session.scalars.call_args.args[0]
    compiled = stmt.compile()
    assert expected_like in compiled.params.values()


# ---------------------------------------------------------------------------
# Date-range filtering + sort direction
# ---------------------------------------------------------------------------


def _compiled_contacts_stmt(**kwargs) -> object:
    db_session = MagicMock()
    db_session.scalar.return_value = 0
    db_session.scalars.return_value = []
    list_contacts(db_session=db_session, page_num=0, page_size=10, **kwargs)
    stmt = db_session.scalars.call_args.args[0]
    return stmt.compile()


def _compiled_orgs_stmt(**kwargs) -> object:
    db_session = MagicMock()
    db_session.scalar.return_value = 0
    db_session.scalars.return_value = []
    list_organizations(db_session=db_session, page_num=0, page_size=10, **kwargs)
    stmt = db_session.scalars.call_args.args[0]
    return stmt.compile()


def test_list_contacts_applies_created_after_filter() -> None:
    value = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    compiled = _compiled_contacts_stmt(created_after=value)
    assert value in compiled.params.values()
    assert ">=" in str(compiled)


def test_list_contacts_applies_updated_after_filter() -> None:
    value = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    compiled = _compiled_contacts_stmt(updated_after=value)
    assert value in compiled.params.values()
    assert ">=" in str(compiled)


def test_list_contacts_applies_updated_before_filter() -> None:
    value = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    compiled = _compiled_contacts_stmt(updated_before=value)
    assert value in compiled.params.values()
    assert "<=" in str(compiled)


def test_list_contacts_before_filter_applied_verbatim_at_midnight() -> None:
    # End-of-day extension for bare dates now happens at the string-parsing
    # boundary (REST / AI tool). The DB layer applies whatever datetime it gets
    # verbatim, so an explicit midnight is NOT silently widened to a full day.
    value = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    compiled = _compiled_contacts_stmt(created_before=value)
    assert value in compiled.params.values()


def test_list_contacts_before_filter_with_time_is_used_as_is() -> None:
    value = datetime(2026, 1, 1, 8, 15, 0, tzinfo=timezone.utc)
    compiled = _compiled_contacts_stmt(created_before=value)
    assert value in compiled.params.values()


def test_list_contacts_combines_date_filters_with_existing_filters() -> None:
    created_after = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tag_id = uuid4()
    compiled = _compiled_contacts_stmt(
        status="lead",
        created_after=created_after,
        tag_ids=[tag_id],
    )
    values = list(compiled.params.values())
    assert created_after in values
    assert "lead" in values


def test_list_contacts_tag_filter_requires_all_tags() -> None:
    # AND/intersection semantics: one correlated EXISTS per distinct tag, so a
    # contact must carry every selected tag to match (not just any one).
    tag_a, tag_b = uuid4(), uuid4()
    compiled = _compiled_contacts_stmt(tag_ids=[tag_a, tag_b])
    sql = str(compiled)
    assert sql.count("EXISTS (SELECT") == 2
    values = list(compiled.params.values())
    assert tag_a in values
    assert tag_b in values


def test_list_contacts_tag_filter_dedupes_repeated_tags() -> None:
    tag_a = uuid4()
    compiled = _compiled_contacts_stmt(tag_ids=[tag_a, tag_a])
    assert str(compiled).count("EXISTS (SELECT") == 1


def test_list_organizations_tag_filter_requires_all_tags() -> None:
    tag_a, tag_b = uuid4(), uuid4()
    compiled = _compiled_orgs_stmt(tag_ids=[tag_a, tag_b])
    assert str(compiled).count("EXISTS (SELECT") == 2


def test_list_organizations_applies_created_before_filter() -> None:
    value = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    compiled = _compiled_orgs_stmt(created_before=value)
    assert value in compiled.params.values()
    assert "<=" in str(compiled)


def test_list_organizations_before_filter_applied_verbatim_at_midnight() -> None:
    # See contacts equivalent: the DB layer no longer widens midnight bounds.
    value = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    compiled = _compiled_orgs_stmt(updated_before=value)
    assert value in compiled.params.values()


def test_list_organizations_applies_updated_after_filter() -> None:
    value = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    compiled = _compiled_orgs_stmt(updated_after=value)
    assert value in compiled.params.values()
    assert ">=" in str(compiled)


def test_build_timestamp_order_clauses_default_is_updated_desc() -> None:
    clauses = _build_timestamp_order_clauses(
        CrmContact.created_at, CrmContact.updated_at, CrmContact.id, None, None
    )
    text = " ".join(str(c) for c in clauses)
    assert "updated_at DESC" in text
    assert "created_at DESC" in text
    # primary is updated_at
    assert "updated_at" in str(clauses[0])
    # deterministic id tie-breaker is appended last, same direction
    assert len(clauses) == 3
    assert "id DESC" in str(clauses[-1])


def test_build_timestamp_order_clauses_created_at_asc() -> None:
    clauses = _build_timestamp_order_clauses(
        CrmContact.created_at, CrmContact.updated_at, CrmContact.id, "created_at", "asc"
    )
    text = " ".join(str(c) for c in clauses)
    assert "created_at ASC" in text
    assert "updated_at ASC" in text
    assert "created_at" in str(clauses[0])
    assert "id ASC" in str(clauses[-1])


def test_build_timestamp_order_clauses_updated_at_asc() -> None:
    clauses = _build_timestamp_order_clauses(
        CrmContact.created_at, CrmContact.updated_at, CrmContact.id, "updated_at", "ASC"
    )
    text = " ".join(str(c) for c in clauses)
    assert "updated_at ASC" in text
    assert "created_at ASC" in text


def test_build_timestamp_order_clauses_lenient_sort_by_falls_back() -> None:
    clauses = _build_timestamp_order_clauses(
        CrmContact.created_at, CrmContact.updated_at, CrmContact.id, "bogus", "desc"
    )
    # unknown sort_by -> updated_at primary
    assert "updated_at" in str(clauses[0])
