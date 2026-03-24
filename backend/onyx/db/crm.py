from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy import case
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql import delete

from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmContactSource
from onyx.db.enums import CrmInteractionType
from onyx.db.enums import CrmOrganizationType
from onyx.db.models import CrmContact
from onyx.db.models import CrmContactOwner
from onyx.db.models import CrmContact__Tag
from onyx.db.models import CrmInteraction
from onyx.db.models import CrmInteractionAttendee
from onyx.db.models import CrmOrganization
from onyx.db.models import CrmOrganization__Tag
from onyx.db.models import CrmSettings
from onyx.db.models import CrmTag
from onyx.db.models import User
from onyx.file_store.utils import build_frontend_file_url


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200
DEFAULT_CONTACT_STAGE_OPTIONS = ["lead", "active", "inactive", "archived"]
DEFAULT_CONTACT_CATEGORY_SUGGESTIONS = [
    "Policy Maker",
    "Journalist",
    "Academic",
    "Allied Org",
    "Lab Member",
]


@dataclass(frozen=True)
class CrmSearchResult:
    entity_type: str
    entity_id: str
    primary_text: str
    secondary_text: str | None
    rank: float
    sort_at: datetime | None


def _normalize_page(page_num: int, page_size: int) -> tuple[int, int]:
    return max(0, page_num), min(max(1, page_size), MAX_PAGE_SIZE)


def _normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    email = email.strip().lower()
    return email or None


def _strip_or_none(name: str | None) -> str | None:
    if name is None:
        return None
    name = name.strip()
    return name or None


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _normalize_stage_options(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw in values:
        candidate = raw.strip().lower()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)

    if not normalized:
        raise ValueError("At least one CRM stage option is required.")
    return normalized


def _normalize_category_suggestions(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw in values:
        candidate = raw.strip()
        dedupe_key = candidate.lower()
        if not candidate or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(candidate)

    return normalized


def _dedupe_uuid_list(values: list[UUID]) -> list[UUID]:
    deduped: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _normalize_status(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("Contact status cannot be empty.")
    return normalized


def _normalize_existing_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _normalize_lookup_name(value: str | None) -> str | None:
    normalized = _strip_or_none(value)
    return normalized.lower() if normalized is not None else None


def _escape_like_query(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def get_or_create_crm_settings(
    db_session: Session,
    commit: bool = True,
) -> CrmSettings:
    settings = db_session.get(CrmSettings, 1)
    if settings is None:
        settings = CrmSettings(
            id=1,
            contact_stage_options=list(DEFAULT_CONTACT_STAGE_OPTIONS),
            contact_category_suggestions=list(DEFAULT_CONTACT_CATEGORY_SUGGESTIONS),
        )
        db_session.add(settings)
        if commit:
            db_session.commit()
        db_session.refresh(settings)
    return settings


def update_crm_settings(
    db_session: Session,
    *,
    updated_by: UUID | None,
    patches: dict[str, Any],
    commit: bool = True,
) -> CrmSettings:
    settings = get_or_create_crm_settings(db_session)
    mutable_fields = {
        "enabled",
        "tier2_enabled",
        "tier3_deals",
        "tier3_custom_fields",
        "contact_stage_options",
        "contact_category_suggestions",
    }

    for key, value in patches.items():
        if key not in mutable_fields:
            continue
        if key == "contact_stage_options":
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError("'contact_stage_options' must be a list of strings.")
            normalized_stage_options = _normalize_stage_options(value)
            existing_stage_values = {
                _normalize_status(stage)
                for stage in db_session.scalars(select(CrmContact.status).distinct())
                if isinstance(stage, str) and stage.strip()
            }
            removed_in_use_stages = sorted(
                existing_stage_values - set(normalized_stage_options)
            )
            if removed_in_use_stages:
                raise ValueError(
                    "Cannot remove CRM stages currently in use: "
                    + ", ".join(removed_in_use_stages)
                )
            settings.contact_stage_options = normalized_stage_options
            continue
        if key == "contact_category_suggestions":
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(
                    "'contact_category_suggestions' must be a list of strings."
                )
            settings.contact_category_suggestions = _normalize_category_suggestions(
                value
            )
            continue
        setattr(settings, key, value)

    settings.updated_by = updated_by
    if commit:
        db_session.commit()
    db_session.refresh(settings)
    return settings


def get_allowed_contact_stages(db_session: Session) -> list[str]:
    settings = get_or_create_crm_settings(db_session)

    if not settings.contact_stage_options:
        return list(DEFAULT_CONTACT_STAGE_OPTIONS)
    return _normalize_stage_options(settings.contact_stage_options)


def validate_stage_string(
    value: str | None,
    *,
    allowed_stages: list[str],
    field_name: str = "status",
) -> str | None:
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"'{field_name}' cannot be empty.")
    if normalized not in allowed_stages:
        allowed = ", ".join(allowed_stages)
        raise ValueError(f"'{field_name}' must be one of: {allowed}.")
    return normalized


def _replace_contact_owners(
    db_session: Session,
    *,
    contact: CrmContact,
    owner_ids: list[UUID],
) -> bool:
    """Replace contact owners. Returns True if any changes were made."""
    deduped_owner_ids = _dedupe_uuid_list(owner_ids)
    existing_owner_ids = set(
        db_session.scalars(
            select(CrmContactOwner.user_id).where(
                CrmContactOwner.contact_id == contact.id
            )
        )
    )
    requested_owner_ids = set(deduped_owner_ids)

    if existing_owner_ids == requested_owner_ids:
        return False

    removed_owner_ids = existing_owner_ids - requested_owner_ids
    if removed_owner_ids:
        db_session.execute(
            delete(CrmContactOwner).where(
                CrmContactOwner.contact_id == contact.id,
                CrmContactOwner.user_id.in_(removed_owner_ids),
            )
        )

    for owner_id in deduped_owner_ids:
        if owner_id in existing_owner_ids:
            continue
        db_session.add(
            CrmContactOwner(
                contact_id=contact.id,
                user_id=owner_id,
            )
        )

    return True


def get_contact_owner_ids(contact_id: UUID, db_session: Session) -> list[UUID]:
    return list(
        db_session.scalars(
            select(CrmContactOwner.user_id)
            .where(CrmContactOwner.contact_id == contact_id)
            .order_by(CrmContactOwner.created_at.asc(), CrmContactOwner.user_id.asc())
        )
    )


def get_contact_by_id(contact_id: UUID, db_session: Session) -> CrmContact | None:
    return db_session.get(CrmContact, contact_id)


def get_contact_by_email(email: str, db_session: Session) -> CrmContact | None:
    normalized_email = _normalize_email(email)
    if normalized_email is None:
        return None

    return db_session.scalar(
        select(CrmContact).where(func.lower(CrmContact.email) == normalized_email)
    )


def list_contacts(
    db_session: Session,
    *,
    page_num: int,
    page_size: int,
    query: str | None = None,
    status: str | None = None,
    category: str | None = None,
    organization_id: UUID | None = None,
    tag_ids: list[UUID] | None = None,
    sort_by: str | None = None,
) -> tuple[list[CrmContact], int]:
    page_num, page_size = _normalize_page(page_num, page_size)

    stmt = select(CrmContact)

    if query:
        query = query.strip()
        if query:
            ts_query = func.websearch_to_tsquery("english", query)
            like_q = f"%{_escape_like_query(query)}%"
            full_name = func.concat_ws(" ", CrmContact.first_name, CrmContact.last_name)
            stmt = stmt.where(
                or_(
                    CrmContact.search_tsv.op("@@")(ts_query),
                    full_name.ilike(like_q, escape="\\"),
                    CrmContact.email.ilike(like_q, escape="\\"),
                )
            )

    if status:
        stmt = stmt.where(CrmContact.status == status.strip().lower())

    if category:
        stmt = stmt.where(CrmContact.category == category.strip())

    if organization_id:
        stmt = stmt.where(CrmContact.organization_id == organization_id)

    if tag_ids:
        stmt = (
            stmt.join(CrmContact__Tag, CrmContact__Tag.contact_id == CrmContact.id)
            .where(CrmContact__Tag.tag_id.in_(tag_ids))
            .distinct()
        )

    total = db_session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort_by == "created_at":
        order_clauses = (CrmContact.created_at.desc(), CrmContact.updated_at.desc())
    else:
        order_clauses = (CrmContact.updated_at.desc(), CrmContact.created_at.desc())

    items = list(
        db_session.scalars(
            stmt.order_by(*order_clauses)
            .offset(page_num * page_size)
            .limit(page_size)
        )
    )
    return items, int(total)


def create_contact(
    db_session: Session,
    *,
    first_name: str,
    last_name: str | None,
    email: str | None,
    phone: str | None,
    title: str | None,
    organization_id: UUID | None,
    source: CrmContactSource | None,
    status: str,
    notes: str | None,
    linkedin_url: str | None,
    location: str | None,
    created_by: UUID | None,
    owner_ids: list[UUID] | None = None,
    category: str | None = None,
    commit: bool = True,
) -> tuple[CrmContact, bool]:
    normalized_first_name = _strip_or_none(first_name)
    if normalized_first_name is None:
        raise ValueError("Contact first name cannot be empty")

    normalized_email = _normalize_email(email)
    if normalized_email:
        existing = get_contact_by_email(normalized_email, db_session)
        if existing is not None:
            return existing, False

    normalized_owner_ids = _dedupe_uuid_list(owner_ids or [])
    normalized_status = _normalize_status(status)

    contact = CrmContact(
        first_name=normalized_first_name,
        last_name=_strip_or_none(last_name),
        email=normalized_email,
        phone=_strip_or_none(phone),
        title=_strip_or_none(title),
        organization_id=organization_id,
        source=source,
        status=normalized_status,
        category=_strip_or_none(category),
        notes=_normalize_text(notes),
        linkedin_url=_strip_or_none(linkedin_url),
        location=_strip_or_none(location),
        created_by=created_by,
    )
    db_session.add(contact)
    db_session.flush()

    for owner_uuid in normalized_owner_ids:
        db_session.add(
            CrmContactOwner(
                contact_id=contact.id,
                user_id=owner_uuid,
            )
        )

    if commit:
        db_session.commit()
    db_session.refresh(contact)
    return contact, True


def update_contact(
    db_session: Session,
    *,
    contact: CrmContact,
    patches: dict,
    commit: bool = True,
) -> tuple[CrmContact, bool]:
    """Update a contact with the given patches.

    Returns (contact, changed) where changed indicates whether any
    field was actually modified.
    """
    mutable_fields = {
        "first_name",
        "last_name",
        "email",
        "phone",
        "title",
        "organization_id",
        "owner_ids",
        "source",
        "status",
        "category",
        "notes",
        "linkedin_url",
        "location",
        "profile_picture_file_id",
    }

    changed = False

    for key, value in patches.items():
        if key not in mutable_fields:
            continue

        if key == "first_name":
            normalized_first_name = _strip_or_none(value)
            if normalized_first_name is None:
                raise ValueError("Contact first name cannot be empty")
            if _strip_or_none(contact.first_name) != normalized_first_name:
                contact.first_name = normalized_first_name
                changed = True
            continue

        if key in {"last_name", "phone", "title", "linkedin_url", "location"}:
            normalized = _strip_or_none(value)
            if _strip_or_none(getattr(contact, key)) != normalized:
                setattr(contact, key, normalized)
                changed = True
            continue

        if key == "notes":
            normalized = _normalize_text(value)
            if _normalize_text(contact.notes) != normalized:
                contact.notes = normalized
                changed = True
            continue

        if key == "email":
            normalized_email = _normalize_email(value)
            if normalized_email is not None:
                existing = get_contact_by_email(normalized_email, db_session)
                if existing is not None and existing.id != contact.id:
                    raise ValueError("A CRM contact with this email already exists.")
            if _normalize_email(contact.email) != normalized_email:
                contact.email = normalized_email
                changed = True
            continue

        if key == "owner_ids":
            if value is None:
                owners_changed = _replace_contact_owners(
                    db_session=db_session,
                    contact=contact,
                    owner_ids=[],
                )
                if owners_changed:
                    changed = True
                continue
            if not isinstance(value, list) or not all(
                isinstance(owner_uuid, UUID) for owner_uuid in value
            ):
                raise ValueError("'owner_ids' must be a list of UUID values.")
            owners_changed = _replace_contact_owners(
                db_session=db_session,
                contact=contact,
                owner_ids=value,
            )
            if owners_changed:
                changed = True
            continue

        if key == "status":
            if not isinstance(value, str):
                raise ValueError("'status' must be a string value.")
            normalized = _normalize_status(value)
            if _normalize_existing_status(contact.status) != normalized:
                contact.status = normalized
                changed = True
            continue

        if key == "category":
            normalized = _strip_or_none(value)
            if _strip_or_none(contact.category) != normalized:
                contact.category = normalized
                changed = True
            continue

        if getattr(contact, key) != value:
            setattr(contact, key, value)
            changed = True

    if changed:
        db_session.flush()
        if commit:
            db_session.commit()
        db_session.refresh(contact)

    return contact, changed


def get_organization_by_id(
    organization_id: UUID, db_session: Session
) -> CrmOrganization | None:
    return db_session.get(CrmOrganization, organization_id)


def get_organization_by_name(name: str, db_session: Session) -> CrmOrganization | None:
    normalized_name = _strip_or_none(name)
    if normalized_name is None:
        return None

    return db_session.scalar(
        select(CrmOrganization).where(
            func.lower(CrmOrganization.name) == normalized_name.lower()
        )
    )


def list_organizations(
    db_session: Session,
    *,
    page_num: int,
    page_size: int,
    query: str | None = None,
    org_type: CrmOrganizationType | None = None,
    tag_ids: list[UUID] | None = None,
    sort_by: str | None = None,
) -> tuple[list[CrmOrganization], int]:
    page_num, page_size = _normalize_page(page_num, page_size)

    stmt = select(CrmOrganization)

    if query:
        query = query.strip()
        if query:
            ts_query = func.websearch_to_tsquery("english", query)
            like_q = f"%{_escape_like_query(query)}%"
            stmt = stmt.where(
                or_(
                    CrmOrganization.search_tsv.op("@@")(ts_query),
                    CrmOrganization.name.ilike(like_q, escape="\\"),
                )
            )

    if org_type is not None:
        stmt = stmt.where(CrmOrganization.type == org_type)

    if tag_ids:
        stmt = (
            stmt.join(
                CrmOrganization__Tag,
                CrmOrganization__Tag.organization_id == CrmOrganization.id,
            )
            .where(CrmOrganization__Tag.tag_id.in_(tag_ids))
            .distinct()
        )

    total = db_session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort_by == "created_at":
        order_clauses = (
            CrmOrganization.created_at.desc(),
            CrmOrganization.updated_at.desc(),
        )
    else:
        order_clauses = (
            CrmOrganization.updated_at.desc(),
            CrmOrganization.created_at.desc(),
        )

    items = list(
        db_session.scalars(
            stmt.order_by(*order_clauses)
            .offset(page_num * page_size)
            .limit(page_size)
        )
    )
    return items, int(total)


def create_organization(
    db_session: Session,
    *,
    name: str,
    website: str | None,
    type: CrmOrganizationType | None,
    sector: str | None,
    location: str | None,
    size: str | None,
    notes: str | None,
    created_by: UUID | None,
    commit: bool = True,
) -> tuple[CrmOrganization, bool]:
    normalized_name = _strip_or_none(name)
    if normalized_name is None:
        raise ValueError("Organization name cannot be empty")

    existing = get_organization_by_name(normalized_name, db_session)
    if existing is not None:
        return existing, False

    organization = CrmOrganization(
        name=normalized_name,
        website=_strip_or_none(website),
        type=type,
        sector=_strip_or_none(sector),
        location=_strip_or_none(location),
        size=_strip_or_none(size),
        notes=_normalize_text(notes),
        created_by=created_by,
    )
    db_session.add(organization)
    db_session.flush()
    if commit:
        db_session.commit()
    db_session.refresh(organization)
    return organization, True


def update_organization(
    db_session: Session,
    *,
    organization: CrmOrganization,
    patches: dict,
    commit: bool = True,
) -> tuple[CrmOrganization, bool]:
    """Update an organization with the given patches.

    Returns (organization, changed) where changed indicates whether any
    field was actually modified.
    """
    mutable_fields = {
        "name",
        "website",
        "type",
        "sector",
        "location",
        "size",
        "notes",
    }

    changed = False

    for key, value in patches.items():
        if key not in mutable_fields:
            continue

        if key == "name":
            normalized_name = _strip_or_none(value)
            if normalized_name is None:
                raise ValueError("Organization name cannot be empty")

            existing = get_organization_by_name(normalized_name, db_session)
            if existing is not None and existing.id != organization.id:
                raise ValueError("A CRM organization with this name already exists.")
            if _strip_or_none(organization.name) != normalized_name:
                organization.name = normalized_name
                changed = True
            continue

        if key in {"website", "sector", "location", "size"}:
            normalized = _strip_or_none(value)
            if _strip_or_none(getattr(organization, key)) != normalized:
                setattr(organization, key, normalized)
                changed = True
            continue

        if key == "notes":
            normalized = _normalize_text(value)
            if _normalize_text(organization.notes) != normalized:
                organization.notes = normalized
                changed = True
            continue

        if getattr(organization, key) != value:
            setattr(organization, key, value)
            changed = True

    if changed:
        db_session.flush()
        if commit:
            db_session.commit()
        db_session.refresh(organization)

    return organization, changed


def list_interactions(
    db_session: Session,
    *,
    page_num: int,
    page_size: int,
    contact_id: UUID | None = None,
    organization_id: UUID | None = None,
    interaction_type: CrmInteractionType | None = None,
) -> tuple[list[CrmInteraction], int]:
    page_num, page_size = _normalize_page(page_num, page_size)

    stmt = select(CrmInteraction)
    if contact_id:
        stmt = stmt.where(CrmInteraction.contact_id == contact_id)
    if organization_id:
        stmt = stmt.where(CrmInteraction.organization_id == organization_id)
    if interaction_type is not None:
        stmt = stmt.where(CrmInteraction.type == interaction_type)

    sort_expr = func.coalesce(CrmInteraction.occurred_at, CrmInteraction.created_at)
    total = db_session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db_session.scalars(
            stmt.order_by(sort_expr.desc())
            .offset(page_num * page_size)
            .limit(page_size)
        )
    )
    return items, int(total)


def get_interaction_by_id(
    interaction_id: UUID, db_session: Session
) -> CrmInteraction | None:
    return db_session.get(CrmInteraction, interaction_id)


def create_interaction(
    db_session: Session,
    *,
    contact_id: UUID | None,
    organization_id: UUID | None,
    logged_by: UUID | None,
    interaction_type: CrmInteractionType,
    title: str,
    summary: str | None,
    occurred_at: datetime | None,
    commit: bool = True,
) -> CrmInteraction:
    normalized_title = _strip_or_none(title)
    if normalized_title is None:
        raise ValueError("Interaction title cannot be empty")

    interaction = CrmInteraction(
        contact_id=contact_id,
        organization_id=organization_id,
        logged_by=logged_by,
        type=interaction_type,
        title=normalized_title,
        summary=_normalize_text(summary),
        occurred_at=occurred_at,
    )
    db_session.add(interaction)
    db_session.flush()
    if commit:
        db_session.commit()
    db_session.refresh(interaction)

    return interaction


def get_interaction_attendees(
    interaction_id: UUID, db_session: Session
) -> list[CrmInteractionAttendee]:
    return list(
        db_session.scalars(
            select(CrmInteractionAttendee)
            .where(CrmInteractionAttendee.interaction_id == interaction_id)
            .order_by(CrmInteractionAttendee.id.asc())
        )
    )


def add_interaction_attendees(
    db_session: Session,
    *,
    interaction_id: UUID,
    user_ids: list[UUID] | None = None,
    contact_ids: list[UUID] | None = None,
    role: CrmAttendeeRole = CrmAttendeeRole.ATTENDEE,
    commit: bool = True,
) -> list[CrmInteractionAttendee]:
    user_ids = user_ids or []
    contact_ids = contact_ids or []

    existing = get_interaction_attendees(interaction_id, db_session)
    existing_by_pair = {
        (attendee.user_id, attendee.contact_id): attendee for attendee in existing
    }

    to_create: list[CrmInteractionAttendee] = []
    updated_existing = False
    for user_id in user_ids:
        key = (user_id, None)
        existing_attendee = existing_by_pair.get(key)
        if existing_attendee is not None:
            if (
                existing_attendee.role != CrmAttendeeRole.ORGANIZER
                and role == CrmAttendeeRole.ORGANIZER
            ):
                existing_attendee.role = CrmAttendeeRole.ORGANIZER
                updated_existing = True
            continue
        to_create.append(
            CrmInteractionAttendee(
                interaction_id=interaction_id,
                user_id=user_id,
                contact_id=None,
                role=role,
            )
        )

    for contact_id in contact_ids:
        key = (None, contact_id)
        existing_attendee = existing_by_pair.get(key)
        if existing_attendee is not None:
            if (
                existing_attendee.role != CrmAttendeeRole.ORGANIZER
                and role == CrmAttendeeRole.ORGANIZER
            ):
                existing_attendee.role = CrmAttendeeRole.ORGANIZER
                updated_existing = True
            continue
        to_create.append(
            CrmInteractionAttendee(
                interaction_id=interaction_id,
                user_id=None,
                contact_id=contact_id,
                role=role,
            )
        )

    if to_create:
        db_session.add_all(to_create)
    if to_create or updated_existing:
        db_session.flush()
        if commit:
            db_session.commit()

    return get_interaction_attendees(interaction_id, db_session)


def list_tags(
    db_session: Session,
    *,
    page_num: int,
    page_size: int,
    query: str | None = None,
) -> tuple[list[CrmTag], int]:
    page_num, page_size = _normalize_page(page_num, page_size)

    stmt = select(CrmTag)
    if query:
        query = query.strip()
        if query:
            like_q = f"%{_escape_like_query(query)}%"
            stmt = stmt.where(CrmTag.name.ilike(like_q, escape="\\"))

    total = db_session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db_session.scalars(
            stmt.order_by(CrmTag.name.asc())
            .offset(page_num * page_size)
            .limit(page_size)
        )
    )
    return items, int(total)


def get_tag_by_id(tag_id: UUID, db_session: Session) -> CrmTag | None:
    return db_session.get(CrmTag, tag_id)


def get_tag_by_name(name: str, db_session: Session) -> CrmTag | None:
    normalized_name = _strip_or_none(name)
    if normalized_name is None:
        return None

    return db_session.scalar(
        select(CrmTag).where(func.lower(CrmTag.name) == normalized_name.lower())
    )


def create_tag(
    db_session: Session,
    *,
    name: str,
    color: str | None,
    commit: bool = True,
) -> tuple[CrmTag, bool]:
    normalized_name = _strip_or_none(name)
    if normalized_name is None:
        raise ValueError("Tag name cannot be empty")

    existing = get_tag_by_name(normalized_name, db_session)
    if existing is not None:
        return existing, False

    tag = CrmTag(name=normalized_name, color=_strip_or_none(color))
    db_session.add(tag)
    db_session.flush()
    if commit:
        db_session.commit()
    db_session.refresh(tag)
    return tag, True


def get_contact_tags(contact_id: UUID, db_session: Session) -> list[CrmTag]:
    return list(
        db_session.scalars(
            select(CrmTag)
            .join(CrmContact__Tag, CrmContact__Tag.tag_id == CrmTag.id)
            .where(CrmContact__Tag.contact_id == contact_id)
            .order_by(CrmTag.name.asc())
        )
    )


def get_organization_tags(
    organization_id: UUID, db_session: Session
) -> list[CrmTag]:
    return list(
        db_session.scalars(
            select(CrmTag)
            .join(CrmOrganization__Tag, CrmOrganization__Tag.tag_id == CrmTag.id)
            .where(CrmOrganization__Tag.organization_id == organization_id)
            .order_by(CrmTag.name.asc())
        )
    )


def add_tag_to_contact(
    db_session: Session,
    *,
    contact_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> None:
    existing = db_session.scalar(
        select(CrmContact__Tag).where(
            and_(CrmContact__Tag.contact_id == contact_id, CrmContact__Tag.tag_id == tag_id)
        )
    )
    if existing:
        return

    db_session.add(CrmContact__Tag(contact_id=contact_id, tag_id=tag_id))
    if commit:
        db_session.commit()


def remove_tag_from_contact(
    db_session: Session,
    *,
    contact_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> None:
    db_session.query(CrmContact__Tag).filter(
        CrmContact__Tag.contact_id == contact_id,
        CrmContact__Tag.tag_id == tag_id,
    ).delete()
    if commit:
        db_session.commit()


def add_tag_to_organization(
    db_session: Session,
    *,
    organization_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> None:
    existing = db_session.scalar(
        select(CrmOrganization__Tag).where(
            and_(
                CrmOrganization__Tag.organization_id == organization_id,
                CrmOrganization__Tag.tag_id == tag_id,
            )
        )
    )
    if existing:
        return

    db_session.add(
        CrmOrganization__Tag(organization_id=organization_id, tag_id=tag_id)
    )
    if commit:
        db_session.commit()


def remove_tag_from_organization(
    db_session: Session,
    *,
    organization_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> None:
    db_session.query(CrmOrganization__Tag).filter(
        CrmOrganization__Tag.organization_id == organization_id,
        CrmOrganization__Tag.tag_id == tag_id,
    ).delete()
    if commit:
        db_session.commit()


def search_crm_entities(
    db_session: Session,
    *,
    query: str,
    entity_types: list[str] | None,
    page_num: int,
    page_size: int,
) -> tuple[list[CrmSearchResult], int]:
    page_num, page_size = _normalize_page(page_num, page_size)
    query = query.strip()
    if not query:
        return [], 0
    escaped_like_query = _escape_like_query(query)

    requested_types = set(entity_types or ["contact", "organization", "interaction", "tag"])

    union_parts: list[str] = []
    if "contact" in requested_types:
        union_parts.append(
            """
            SELECT
                'contact'::text AS entity_type,
                c.id::text AS entity_id,
                trim(concat_ws(' ', c.first_name, c.last_name)) AS primary_text,
                c.email AS secondary_text,
                c.updated_at AS sort_at,
                ts_rank_cd(c.search_tsv, websearch_to_tsquery('english', :query)) AS rank
            FROM crm_contact c
            WHERE c.search_tsv @@ websearch_to_tsquery('english', :query)
            """
        )

    if "organization" in requested_types:
        union_parts.append(
            """
            SELECT
                'organization'::text AS entity_type,
                o.id::text AS entity_id,
                o.name AS primary_text,
                o.website AS secondary_text,
                o.updated_at AS sort_at,
                ts_rank_cd(o.search_tsv, websearch_to_tsquery('english', :query)) AS rank
            FROM crm_organization o
            WHERE o.search_tsv @@ websearch_to_tsquery('english', :query)
            """
        )

    if "interaction" in requested_types:
        union_parts.append(
            """
            SELECT
                'interaction'::text AS entity_type,
                i.id::text AS entity_id,
                i.title AS primary_text,
                i.summary AS secondary_text,
                COALESCE(i.occurred_at, i.created_at) AS sort_at,
                ts_rank_cd(i.search_tsv, websearch_to_tsquery('english', :query)) AS rank
            FROM crm_interaction i
            WHERE i.search_tsv @@ websearch_to_tsquery('english', :query)
            """
        )

    if "tag" in requested_types:
        union_parts.append(
            """
            SELECT
                'tag'::text AS entity_type,
                t.id::text AS entity_id,
                t.name AS primary_text,
                t.color AS secondary_text,
                t.created_at AS sort_at,
                CASE
                    WHEN lower(t.name) = lower(:query) THEN 1.0
                    WHEN lower(t.name) LIKE lower(:query || '%') THEN 0.75
                    ELSE 0.5
                END AS rank
            FROM crm_tag t
            WHERE t.name ILIKE ('%' || :escaped_like_query || '%') ESCAPE '\\'
            """
        )

    if not union_parts:
        return [], 0

    union_sql = " UNION ALL ".join(union_parts)

    count_query = text(f"SELECT COUNT(*) FROM ({union_sql}) AS crm_search")
    total = db_session.execute(
        count_query, {"query": query, "escaped_like_query": escaped_like_query}
    ).scalar_one()

    rows = db_session.execute(
        text(
            f"""
            SELECT entity_type, entity_id, primary_text, secondary_text, sort_at, rank
            FROM ({union_sql}) AS crm_search
            ORDER BY rank DESC, sort_at DESC NULLS LAST, primary_text ASC
            OFFSET :offset
            LIMIT :limit
            """
        ),
        {
            "query": query,
            "escaped_like_query": escaped_like_query,
            "offset": page_num * page_size,
            "limit": page_size,
        },
    ).mappings()

    results = [
        CrmSearchResult(
            entity_type=str(row["entity_type"]),
            entity_id=str(row["entity_id"]),
            primary_text=str(row["primary_text"] or ""),
            secondary_text=(
                str(row["secondary_text"]) if row["secondary_text"] is not None else None
            ),
            rank=float(row["rank"] or 0),
            sort_at=row["sort_at"],
        )
        for row in rows
    ]
    return results, int(total)


def find_contacts_for_attendee_resolution(
    db_session: Session,
    *,
    token: str,
    max_results: int = 5,
) -> list[CrmContact]:
    token = token.strip()
    if not token:
        return []

    token_lower = token.lower()
    escaped_token = _escape_like_query(token)
    like_q = f"%{escaped_token}%"
    full_name = func.concat_ws(" ", CrmContact.first_name, CrmContact.last_name)
    priority = case(
        (func.lower(CrmContact.email) == token_lower, 0),
        (func.lower(full_name) == token_lower, 1),
        (full_name.ilike(like_q, escape="\\"), 2),
        (CrmContact.first_name.ilike(like_q, escape="\\"), 3),
        (CrmContact.last_name.ilike(like_q, escape="\\"), 3),
        (CrmContact.email.ilike(like_q, escape="\\"), 4),
        else_=5,
    )

    return list(
        db_session.scalars(
            select(CrmContact)
            .where(
                or_(
                    func.lower(CrmContact.email) == token_lower,
                    func.lower(full_name) == token_lower,
                    full_name.ilike(like_q, escape="\\"),
                    CrmContact.first_name.ilike(like_q, escape="\\"),
                    CrmContact.last_name.ilike(like_q, escape="\\"),
                    CrmContact.email.ilike(like_q, escape="\\"),
                )
            )
            .order_by(priority.asc(), CrmContact.updated_at.desc())
            .limit(max_results)
        )
    )


def find_users_for_attendee_resolution(
    db_session: Session,
    *,
    token: str,
    max_results: int = 5,
) -> list[User]:
    token = token.strip()
    if not token:
        return []

    token_lower = token.lower()
    escaped_token = _escape_like_query(token)
    like_q = f"%{escaped_token}%"
    priority = case(
        (func.lower(User.email) == token_lower, 0),
        (func.lower(User.personal_name) == token_lower, 1),
        (User.personal_name.ilike(like_q, escape="\\"), 2),
        (User.email.ilike(like_q, escape="\\"), 3),
        else_=4,
    )

    return list(
        db_session.scalars(
            select(User)
            .where(
                or_(
                    func.lower(User.email) == token_lower,
                    User.email.ilike(like_q, escape="\\"),
                    User.personal_name.ilike(like_q, escape="\\"),
                )
            )
            .order_by(priority.asc(), User.email.asc())
            .limit(max_results)
        ).unique()
    )


def export_all_organizations(db_session: Session) -> list[dict]:
    """Export all organizations with tags for CSV."""
    orgs = list(
        db_session.scalars(
            select(CrmOrganization).order_by(CrmOrganization.name.asc())
        )
    )
    if not orgs:
        return []

    org_ids = [org.id for org in orgs]

    # Bulk-fetch tags keyed by organization ID
    tag_rows = db_session.execute(
        select(CrmOrganization__Tag.organization_id, CrmTag.name)
        .join(CrmTag, CrmOrganization__Tag.tag_id == CrmTag.id)
        .where(CrmOrganization__Tag.organization_id.in_(org_ids))
        .order_by(CrmTag.name.asc())
    ).all()
    org_tags: dict[UUID, list[str]] = {}
    for org_id, tag_name in tag_rows:
        org_tags.setdefault(org_id, []).append(tag_name)

    # Bulk-fetch creator emails
    creator_ids = [org.created_by for org in orgs if org.created_by is not None]
    creator_emails: dict[UUID, str] = {}
    if creator_ids:
        user_rows = db_session.execute(
            select(User.id, User.email).where(User.id.in_(creator_ids))
        ).all()
        creator_emails = {uid: email for uid, email in user_rows}

    results: list[dict] = []
    for org in orgs:
        results.append(
            {
                "id": str(org.id),
                "name": _strip_or_none(org.name) or "",
                "website": _strip_or_none(org.website) or "",
                "type": org.type.value if org.type is not None else "",
                "sector": _strip_or_none(org.sector) or "",
                "location": _strip_or_none(org.location) or "",
                "size": _strip_or_none(org.size) or "",
                "notes": _normalize_text(org.notes) or "",
                "tags": "|".join(org_tags.get(org.id, [])),
                "created_by": creator_emails.get(org.created_by, "")
                if org.created_by is not None
                else "",
                "created_at": str(org.created_at) if org.created_at is not None else "",
                "updated_at": str(org.updated_at) if org.updated_at is not None else "",
            }
        )
    return results


def export_all_contacts(db_session: Session) -> list[dict]:
    """Export all contacts with org name, owner emails, and tags for CSV."""
    contacts = list(
        db_session.scalars(
            select(CrmContact).order_by(
                CrmContact.last_name.asc(), CrmContact.first_name.asc()
            )
        )
    )
    if not contacts:
        return []

    contact_ids = [c.id for c in contacts]

    # Bulk-fetch organization names
    org_ids = list(
        {c.organization_id for c in contacts if c.organization_id is not None}
    )
    org_names: dict[UUID, str] = {}
    if org_ids:
        org_rows = db_session.execute(
            select(CrmOrganization.id, CrmOrganization.name).where(
                CrmOrganization.id.in_(org_ids)
            )
        ).all()
        org_names = {oid: name for oid, name in org_rows}

    # Bulk-fetch owner emails keyed by contact ID
    owner_rows = db_session.execute(
        select(CrmContactOwner.contact_id, User.email)
        .join(User, CrmContactOwner.user_id == User.id)
        .where(CrmContactOwner.contact_id.in_(contact_ids))
        .order_by(User.email.asc())
    ).all()
    contact_owners: dict[UUID, list[str]] = {}
    for cid, email in owner_rows:
        contact_owners.setdefault(cid, []).append(email)

    # Bulk-fetch tags keyed by contact ID
    tag_rows = db_session.execute(
        select(CrmContact__Tag.contact_id, CrmTag.name)
        .join(CrmTag, CrmContact__Tag.tag_id == CrmTag.id)
        .where(CrmContact__Tag.contact_id.in_(contact_ids))
        .order_by(CrmTag.name.asc())
    ).all()
    contact_tags: dict[UUID, list[str]] = {}
    for cid, tag_name in tag_rows:
        contact_tags.setdefault(cid, []).append(tag_name)

    # Bulk-fetch creator emails
    creator_ids = [c.created_by for c in contacts if c.created_by is not None]
    creator_emails: dict[UUID, str] = {}
    if creator_ids:
        user_rows = db_session.execute(
            select(User.id, User.email).where(User.id.in_(creator_ids))
        ).all()
        creator_emails = {uid: email for uid, email in user_rows}

    results: list[dict] = []
    for c in contacts:
        results.append(
            {
                "id": str(c.id),
                "first_name": _strip_or_none(c.first_name) or "",
                "last_name": _strip_or_none(c.last_name) or "",
                "email": _normalize_email(c.email) or "",
                "phone": _strip_or_none(c.phone) or "",
                "title": _strip_or_none(c.title) or "",
                "organization_name": _strip_or_none(org_names.get(c.organization_id))
                if c.organization_id is not None
                else "",
                "owner_emails": "|".join(contact_owners.get(c.id, [])),
                "source": c.source.value if c.source is not None else "",
                "status": _normalize_existing_status(c.status) or "",
                "category": _strip_or_none(c.category) or "",
                "notes": _normalize_text(c.notes) or "",
                "linkedin_url": _strip_or_none(c.linkedin_url) or "",
                "location": _strip_or_none(c.location) or "",
                "profile_picture_url": (
                    build_frontend_file_url(c.profile_picture_file_id)
                    if c.profile_picture_file_id
                    else ""
                ),
                "tags": "|".join(contact_tags.get(c.id, [])),
                "created_by": creator_emails.get(c.created_by, "")
                if c.created_by is not None
                else "",
                "created_at": str(c.created_at) if c.created_at is not None else "",
                "updated_at": str(c.updated_at) if c.updated_at is not None else "",
            }
        )
    return results


def export_all_interactions(db_session: Session) -> list[dict]:
    """Export all interactions with contact email and org name for CSV."""
    sort_expr = func.coalesce(CrmInteraction.occurred_at, CrmInteraction.created_at)
    interactions = list(
        db_session.scalars(
            select(CrmInteraction).order_by(sort_expr.desc())
        )
    )
    if not interactions:
        return []

    # Bulk-fetch contact emails
    contact_ids = list(
        {i.contact_id for i in interactions if i.contact_id is not None}
    )
    contact_emails: dict[UUID, str] = {}
    if contact_ids:
        contact_rows = db_session.execute(
            select(CrmContact.id, CrmContact.email).where(
                CrmContact.id.in_(contact_ids)
            )
        ).all()
        contact_emails = {cid: email or "" for cid, email in contact_rows}

    # Bulk-fetch organization names
    org_ids = list(
        {i.organization_id for i in interactions if i.organization_id is not None}
    )
    org_names: dict[UUID, str] = {}
    if org_ids:
        org_rows = db_session.execute(
            select(CrmOrganization.id, CrmOrganization.name).where(
                CrmOrganization.id.in_(org_ids)
            )
        ).all()
        org_names = {oid: name for oid, name in org_rows}

    # Bulk-fetch logger emails
    logger_ids = list(
        {i.logged_by for i in interactions if i.logged_by is not None}
    )
    logger_emails: dict[UUID, str] = {}
    if logger_ids:
        user_rows = db_session.execute(
            select(User.id, User.email).where(User.id.in_(logger_ids))
        ).all()
        logger_emails = {uid: email for uid, email in user_rows}

    # Bulk-fetch all attendees for exported interactions
    interaction_ids = [i.id for i in interactions]
    attendees: list[CrmInteractionAttendee] = []
    if interaction_ids:
        attendees = list(
            db_session.scalars(
                select(CrmInteractionAttendee).where(
                    CrmInteractionAttendee.interaction_id.in_(interaction_ids)
                )
            )
        )

    # Build user-email and contact-email maps for attendees
    attendee_user_ids = list(
        {a.user_id for a in attendees if a.user_id is not None}
    )
    attendee_user_emails: dict[UUID, str] = {}
    if attendee_user_ids:
        rows = db_session.execute(
            select(User.id, User.email).where(User.id.in_(attendee_user_ids))
        ).all()
        attendee_user_emails = {uid: email for uid, email in rows}

    attendee_contact_ids = list(
        {a.contact_id for a in attendees if a.contact_id is not None}
    )
    attendee_contact_emails: dict[UUID, str | None] = {}
    if attendee_contact_ids:
        rows = db_session.execute(
            select(CrmContact.id, CrmContact.email).where(
                CrmContact.id.in_(attendee_contact_ids)
            )
        ).all()
        attendee_contact_emails = {cid: email for cid, email in rows}

    # Group attendees by interaction_id
    attendees_by_interaction: dict[UUID, list[CrmInteractionAttendee]] = {}
    for a in attendees:
        attendees_by_interaction.setdefault(a.interaction_id, []).append(a)

    results: list[dict] = []
    for i in interactions:
        ia_list = attendees_by_interaction.get(i.id, [])

        organizer_users: list[str] = []
        organizer_contacts: list[str] = []
        attendee_users: list[str] = []
        attendee_contacts: list[str] = []

        for a in ia_list:
            if a.role == CrmAttendeeRole.ORGANIZER:
                if a.user_id is not None:
                    email = attendee_user_emails.get(a.user_id, "")
                    if email:
                        organizer_users.append(email)
                if a.contact_id is not None:
                    email = attendee_contact_emails.get(a.contact_id)
                    if email:
                        organizer_contacts.append(email)
            else:
                # ATTENDEE and OBSERVER both fold into attendee columns
                if a.user_id is not None:
                    email = attendee_user_emails.get(a.user_id, "")
                    if email:
                        attendee_users.append(email)
                if a.contact_id is not None:
                    email = attendee_contact_emails.get(a.contact_id)
                    if email:
                        attendee_contacts.append(email)

        results.append(
            {
                "id": str(i.id),
                "type": i.type.value if i.type is not None else "",
                "title": _strip_or_none(i.title) or "",
                "summary": _normalize_text(i.summary) or "",
                "contact_email": _normalize_email(contact_emails.get(i.contact_id))
                if i.contact_id is not None
                else "",
                "organization_name": _strip_or_none(org_names.get(i.organization_id))
                if i.organization_id is not None
                else "",
                "organizer_users": "|".join(organizer_users),
                "organizer_contacts": "|".join(organizer_contacts),
                "attendee_users": "|".join(attendee_users),
                "attendee_contacts": "|".join(attendee_contacts),
                "occurred_at": str(i.occurred_at)
                if i.occurred_at is not None
                else "",
                "logged_by": logger_emails.get(i.logged_by, "")
                if i.logged_by is not None
                else "",
                "created_at": str(i.created_at) if i.created_at is not None else "",
                "updated_at": str(i.updated_at) if i.updated_at is not None else "",
            }
        )
    return results


def build_org_name_lookup(db_session: Session) -> dict[str, UUID]:
    """Build {lowercase_name: org_id} lookup dict."""
    rows = db_session.execute(
        select(CrmOrganization.id, CrmOrganization.name)
    ).all()
    result: dict[str, UUID] = {}
    for oid, name in rows:
        normalized_name = _normalize_lookup_name(name)
        if normalized_name is not None:
            result[normalized_name] = oid
    return result


def build_contact_email_lookup(db_session: Session) -> dict[str, UUID]:
    """Build {lowercase_email: contact_id} lookup dict."""
    rows = db_session.execute(
        select(CrmContact.id, CrmContact.email).where(
            CrmContact.email.isnot(None)
        )
    ).all()
    result: dict[str, UUID] = {}
    for cid, email in rows:
        normalized_email = _normalize_email(email)
        if normalized_email is not None:
            result[normalized_email] = cid
    return result


def build_user_email_lookup(db_session: Session) -> dict[str, UUID]:
    """Build {lowercase_email: user_id} lookup dict for resolving owner_emails."""
    rows = db_session.execute(
        select(User.id, User.email)
    ).all()
    result: dict[str, UUID] = {}
    for uid, email in rows:
        normalized_email = _normalize_email(email)
        if normalized_email is not None:
            result[normalized_email] = uid
    return result


def ensure_tags_exist(
    db_session: Session,
    tag_names: list[str],
    commit: bool = True,
) -> dict[str, UUID]:
    """Look up or create tags by name. Returns {lowercase_name: tag_id}."""
    result: dict[str, UUID] = {}
    for name in tag_names:
        name = name.strip()
        if not name:
            continue
        tag, _created = create_tag(
            db_session, name=name, color=None, commit=False
        )
        result[name.lower()] = tag.id
    db_session.flush()
    if commit:
        db_session.commit()
    return result
