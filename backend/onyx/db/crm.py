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


def _escape_like_query(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def get_or_create_crm_settings(db_session: Session) -> CrmSettings:
    settings = db_session.get(CrmSettings, 1)
    if settings is None:
        settings = CrmSettings(
            id=1,
            contact_stage_options=list(DEFAULT_CONTACT_STAGE_OPTIONS),
            contact_category_suggestions=list(DEFAULT_CONTACT_CATEGORY_SUGGESTIONS),
        )
        db_session.add(settings)
        db_session.commit()
        db_session.refresh(settings)
    return settings


def update_crm_settings(
    db_session: Session,
    *,
    updated_by: UUID | None,
    patches: dict[str, Any],
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
) -> None:
    deduped_owner_ids = _dedupe_uuid_list(owner_ids)
    existing_owner_ids = set(
        db_session.scalars(
            select(CrmContactOwner.user_id).where(
                CrmContactOwner.contact_id == contact.id
            )
        )
    )
    requested_owner_ids = set(deduped_owner_ids)

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

    db_session.commit()
    db_session.refresh(contact)
    return contact, True


def update_contact(
    db_session: Session,
    *,
    contact: CrmContact,
    patches: dict,
) -> CrmContact:
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
    }

    for key, value in patches.items():
        if key not in mutable_fields:
            continue

        if key == "first_name":
            normalized_first_name = _strip_or_none(value)
            if normalized_first_name is None:
                raise ValueError("Contact first name cannot be empty")
            contact.first_name = normalized_first_name
            continue

        if key in {"last_name", "phone", "title", "linkedin_url", "location"}:
            setattr(contact, key, _strip_or_none(value))
            continue

        if key == "notes":
            contact.notes = _normalize_text(value)
            continue

        if key == "email":
            normalized_email = _normalize_email(value)
            if normalized_email is not None:
                existing = get_contact_by_email(normalized_email, db_session)
                if existing is not None and existing.id != contact.id:
                    raise ValueError("A CRM contact with this email already exists.")
            contact.email = normalized_email
            continue

        if key == "owner_ids":
            if value is None:
                _replace_contact_owners(
                    db_session=db_session,
                    contact=contact,
                    owner_ids=[],
                )
                continue
            if not isinstance(value, list) or not all(
                isinstance(owner_uuid, UUID) for owner_uuid in value
            ):
                raise ValueError("'owner_ids' must be a list of UUID values.")
            _replace_contact_owners(
                db_session=db_session,
                contact=contact,
                owner_ids=value,
            )
            continue

        if key == "status":
            if not isinstance(value, str):
                raise ValueError("'status' must be a string value.")
            contact.status = _normalize_status(value)
            continue

        if key == "category":
            contact.category = _strip_or_none(value)
            continue

        setattr(contact, key, value)

    db_session.commit()
    db_session.refresh(contact)
    return contact


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
    db_session.commit()
    db_session.refresh(organization)
    return organization, True


def update_organization(
    db_session: Session,
    *,
    organization: CrmOrganization,
    patches: dict,
) -> CrmOrganization:
    mutable_fields = {
        "name",
        "website",
        "type",
        "sector",
        "location",
        "size",
        "notes",
    }

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
            organization.name = normalized_name
            continue

        if key in {"website", "sector", "location", "size"}:
            setattr(organization, key, _strip_or_none(value))
            continue

        if key == "notes":
            organization.notes = _normalize_text(value)
            continue

        setattr(organization, key, value)

    db_session.commit()
    db_session.refresh(organization)
    return organization


def list_interactions(
    db_session: Session,
    *,
    page_num: int,
    page_size: int,
    contact_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> tuple[list[CrmInteraction], int]:
    page_num, page_size = _normalize_page(page_num, page_size)

    stmt = select(CrmInteraction)
    if contact_id:
        stmt = stmt.where(CrmInteraction.contact_id == contact_id)
    if organization_id:
        stmt = stmt.where(CrmInteraction.organization_id == organization_id)

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
) -> tuple[CrmTag, bool]:
    normalized_name = _strip_or_none(name)
    if normalized_name is None:
        raise ValueError("Tag name cannot be empty")

    existing = get_tag_by_name(normalized_name, db_session)
    if existing is not None:
        return existing, False

    tag = CrmTag(name=normalized_name, color=_strip_or_none(color))
    db_session.add(tag)
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
) -> None:
    existing = db_session.scalar(
        select(CrmContact__Tag).where(
            and_(CrmContact__Tag.contact_id == contact_id, CrmContact__Tag.tag_id == tag_id)
        )
    )
    if existing:
        return

    db_session.add(CrmContact__Tag(contact_id=contact_id, tag_id=tag_id))
    db_session.commit()


def remove_tag_from_contact(
    db_session: Session,
    *,
    contact_id: UUID,
    tag_id: UUID,
) -> None:
    db_session.query(CrmContact__Tag).filter(
        CrmContact__Tag.contact_id == contact_id,
        CrmContact__Tag.tag_id == tag_id,
    ).delete()
    db_session.commit()


def add_tag_to_organization(
    db_session: Session,
    *,
    organization_id: UUID,
    tag_id: UUID,
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
    db_session.commit()


def remove_tag_from_organization(
    db_session: Session,
    *,
    organization_id: UUID,
    tag_id: UUID,
) -> None:
    db_session.query(CrmOrganization__Tag).filter(
        CrmOrganization__Tag.organization_id == organization_id,
        CrmOrganization__Tag.tag_id == tag_id,
    ).delete()
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
