from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.db.crm import create_contact
from onyx.db.crm import create_interaction
from onyx.db.crm import create_organization
from onyx.db.crm import create_tag
from onyx.db.crm import find_contacts_for_attendee_resolution
from onyx.db.crm import find_users_for_attendee_resolution
from onyx.db.crm import get_contact_by_email
from onyx.db.crm import get_organization_by_name
from onyx.db.crm import list_contacts
from onyx.db.crm import list_organizations
from onyx.db.crm import list_tags
from onyx.db.crm import search_crm_entities
from onyx.db.crm import update_contact
from onyx.db.crm import update_organization
from onyx.db.enums import CrmInteractionType
from onyx.db.models import CrmContact
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

    updated = update_contact(
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

    updated = update_organization(
        db_session=db_session,
        organization=organization,
        patches={"name": "  New Name  ", "notes": "  Updated notes  "},
    )

    assert updated is organization
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
    db_session.scalars.return_value = [user]
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
