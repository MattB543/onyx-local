from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_, select, text, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import delete, expression

from onyx.configs.constants import (
    ANONYMOUS_USER_EMAIL,
    DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN,
    NO_AUTH_PLACEHOLDER_USER_EMAIL,
)
from onyx.db.enums import (
    AccountType,
    CrmAttendeeRole,
    CrmContactSource,
    CrmInteractionType,
    CrmOrganizationType,
)
from onyx.db.models import (
    CrmContact,
    CrmContact__Tag,
    CrmContactOwner,
    CrmInteraction,
    CrmInteractionAttendee,
    CrmOrganization,
    CrmOrganization__Tag,
    CrmSettings,
    CrmTag,
    User,
)
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


@dataclass(frozen=True)
class CrmPrincipalCount:
    name: str
    contact_count: int


def _normalize_page(page_num: int, page_size: int) -> tuple[int, int]:
    return max(0, page_num), min(max(1, page_size), MAX_PAGE_SIZE)


def _apply_timestamp_filters(
    stmt: Any,
    *,
    created_col: Any,
    updated_col: Any,
    created_after: datetime | None,
    created_before: datetime | None,
    updated_after: datetime | None,
    updated_before: datetime | None,
) -> Any:
    # Bounds are inclusive. End-of-day extension for date-only *_before inputs is
    # handled at the string-parsing boundary (REST / AI tool), so the datetimes
    # received here are applied verbatim.
    if created_after is not None:
        stmt = stmt.where(created_col >= created_after)
    if created_before is not None:
        stmt = stmt.where(created_col <= created_before)
    if updated_after is not None:
        stmt = stmt.where(updated_col >= updated_after)
    if updated_before is not None:
        stmt = stmt.where(updated_col <= updated_before)
    return stmt


def _build_timestamp_order_clauses(
    created_col: Any,
    updated_col: Any,
    id_col: Any,
    sort_by: str | None,
    sort_dir: str | None,
) -> tuple[Any, Any, Any]:
    """Return order_by clauses: primary = chosen field, secondary = the other
    field, tertiary = primary key. The id tie-breaker keeps offset pagination
    deterministic when rows share both timestamps (e.g. batch-created rows).
    All clauses use the same direction. Defaults: updated_at desc."""
    direction = "asc" if (sort_dir or "desc").strip().lower() == "asc" else "desc"
    if (sort_by or "").strip().lower() == "created_at":
        primary, secondary = created_col, updated_col
    else:
        primary, secondary = updated_col, created_col
    if direction == "asc":
        return (primary.asc(), secondary.asc(), id_col.asc())
    return (primary.desc(), secondary.desc(), id_col.desc())


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


def _normalize_us_state(value: str | None) -> str | None:
    # 2-letter US state code is guidance, not a constraint: uppercase a bare
    # 2-letter alphabetic value, otherwise keep the (stripped) text as-is.
    normalized = _strip_or_none(value)
    if normalized is None:
        return None
    if len(normalized) == 2 and normalized.isalpha():
        return normalized.upper()
    return normalized


def _require_at_least_one_name(first_name: str | None, last_name: str | None) -> None:
    if _strip_or_none(first_name) is None and _strip_or_none(last_name) is None:
        raise ValueError("A contact requires at least a first name or a last name.")


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
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contact_full_name(contact: CrmContact) -> str:
    first_name = (contact.first_name or "").strip()
    last_name = (contact.last_name or "").strip()
    return " ".join([part for part in [first_name, last_name] if part]).strip()


def _principal_matches(normalized_principal: str) -> Any:
    """Trimmed, case-insensitive match on a contact's principal text."""
    return func.lower(func.btrim(CrmContact.principal)) == normalized_principal


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


def get_contact_category_options(db_session: Session) -> list[str]:
    settings = get_or_create_crm_settings(db_session)

    if not settings.contact_category_suggestions:
        return list(DEFAULT_CONTACT_CATEGORY_SUGGESTIONS)
    return _normalize_category_suggestions(settings.contact_category_suggestions)


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
    name: str | None = None,
    status: str | None = None,
    category: str | None = None,
    organization_id: UUID | None = None,
    principal: str | None = None,
    principal_contact_id: UUID | None = None,
    tag_ids: list[UUID] | None = None,
    owner_ids: list[UUID] | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
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
                    CrmContact.principal.ilike(like_q, escape="\\"),
                )
            )

    name = _strip_or_none(name)
    if name:
        full_name = func.concat_ws(" ", CrmContact.first_name, CrmContact.last_name)
        stmt = stmt.where(full_name.ilike(f"%{_escape_like_query(name)}%", escape="\\"))

    if status:
        stmt = stmt.where(CrmContact.status == status.strip().lower())

    if category:
        stmt = stmt.where(CrmContact.category == category.strip())

    if organization_id:
        stmt = stmt.where(CrmContact.organization_id == organization_id)

    normalized_principal = _normalize_lookup_name(principal)
    if normalized_principal:
        stmt = stmt.where(_principal_matches(normalized_principal))

    if principal_contact_id:
        stmt = stmt.where(CrmContact.principal_contact_id == principal_contact_id)

    if tag_ids:
        # Require ALL selected tags (intersection): one EXISTS per distinct tag.
        for tag_id in dict.fromkeys(tag_ids):
            stmt = stmt.where(
                select(CrmContact__Tag.contact_id)
                .where(
                    CrmContact__Tag.contact_id == CrmContact.id,
                    CrmContact__Tag.tag_id == tag_id,
                )
                .exists()
            )

    if owner_ids:
        stmt = stmt.where(
            select(CrmContactOwner.contact_id)
            .where(
                CrmContactOwner.contact_id == CrmContact.id,
                CrmContactOwner.user_id.in_(owner_ids),
            )
            .exists()
        )

    stmt = _apply_timestamp_filters(
        stmt,
        created_col=CrmContact.created_at,
        updated_col=CrmContact.updated_at,
        created_after=created_after,
        created_before=created_before,
        updated_after=updated_after,
        updated_before=updated_before,
    )

    total = db_session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    order_clauses = _build_timestamp_order_clauses(
        CrmContact.created_at, CrmContact.updated_at, CrmContact.id, sort_by, sort_dir
    )

    items = list(
        db_session.scalars(
            stmt.order_by(*order_clauses).offset(page_num * page_size).limit(page_size)
        )
    )
    return items, int(total)


def list_contact_principals(
    db_session: Session, organization_id: UUID | None = None
) -> list[CrmPrincipalCount]:
    """Distinct contact principals, matched like the list_contacts filter
    (trimmed, case-insensitive). Each group shows its most common spelling.
    With organization_id, only that organization's contacts count."""
    trimmed = func.btrim(CrmContact.principal)
    display_name = func.mode().within_group(trimmed.asc())
    stmt = select(display_name, func.count()).where(
        func.nullif(trimmed, "").is_not(None)
    )
    if organization_id:
        stmt = stmt.where(CrmContact.organization_id == organization_id)
    rows = db_session.execute(
        stmt.group_by(func.lower(trimmed)).order_by(func.lower(display_name))
    ).all()
    return [CrmPrincipalCount(name=name, contact_count=count) for name, count in rows]


# Honorifics and titles that do not identify the official.
_PRINCIPAL_TITLE_WORDS = frozenset(
    {
        "the",
        "hon",
        "honorable",
        "rep",
        "representative",
        "congressman",
        "congresswoman",
        "congressmember",
        "sen",
        "senator",
        "gov",
        "governor",
        "dr",
        "mr",
        "mrs",
        "ms",
        "jr",
        "sr",
        "office",
        "of",
    }
)


def _principal_surname(principal: str) -> str | None:
    words = [
        word
        for word in "".join(
            char if char.isalnum() else " " for char in principal.lower()
        ).split()
        if word not in _PRINCIPAL_TITLE_WORDS
    ]
    return words[-1] if words else None


def find_similar_principals(
    db_session: Session, principal: str, limit: int = 5
) -> list[CrmPrincipalCount]:
    """Existing principals that may be the same official under another spelling
    (e.g. "Rep. Sara Jacobs" and "Sara Jacobs"): the same surname once titles
    are removed. The exact (case-insensitive) spelling is excluded."""
    normalized = _normalize_lookup_name(principal)
    surname = _principal_surname(normalized) if normalized else None
    if surname is None:
        return []
    similar = [
        row
        for row in list_contact_principals(db_session)
        if row.name.strip().lower() != normalized
        and _principal_surname(row.name) == surname
    ]
    similar.sort(key=lambda row: -row.contact_count)
    return similar[:limit]


def _linked_principal_name(
    db_session: Session,
    contact_id: UUID | None,
    official_id: UUID,
    *,
    new_link: bool,
) -> str:
    """The principal text of a contact linked to official_id: the official's
    full name. A new link reads the official FOR SHARE: a concurrent rename
    then waits and also renames this contact, or it commits first and this
    read sees the new name."""
    if official_id == contact_id:
        raise ValueError("A contact cannot be its own principal.")
    stmt = (
        select(CrmContact)
        .where(CrmContact.id == official_id)
        .execution_options(populate_existing=True)
    )
    if new_link:
        stmt = stmt.with_for_update(read=True)
    official = db_session.scalars(stmt).first()
    if official is None:
        raise ValueError("The principal contact does not exist.")
    return contact_full_name(official)


def _apply_principal_patches(
    db_session: Session, contact: CrmContact, patches: dict
) -> bool:
    """Apply 'principal' and 'principal_contact_id' together. A link sets the
    text to the official's name, and new text that names someone else drops
    the link. Returns True if either field changed."""
    principal = _strip_or_none(patches.get("principal", contact.principal))
    official_id = patches.get("principal_contact_id", contact.principal_contact_id)
    if official_id is not None:
        official_name = _linked_principal_name(
            db_session,
            contact.id,
            official_id,
            new_link=official_id != contact.principal_contact_id,
        )
        if (
            "principal_contact_id" in patches
            or _normalize_lookup_name(principal) == official_name.lower()
        ):
            principal = official_name
        else:
            official_id = None

    changed = False
    if _strip_or_none(contact.principal) != principal:
        contact.principal = principal
        changed = True
    if contact.principal_contact_id != official_id:
        contact.principal_contact_id = official_id
        changed = True
    return changed


def create_contact(
    db_session: Session,
    *,
    first_name: str | None,
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
    party_affiliation: str | None = None,
    us_state: str | None = None,
    principal: str | None = None,
    principal_contact_id: UUID | None = None,
    profile_picture_file_id: str | None = None,
    commit: bool = True,
) -> tuple[CrmContact, bool]:
    normalized_first_name = _strip_or_none(first_name)
    normalized_last_name = _strip_or_none(last_name)
    _require_at_least_one_name(normalized_first_name, normalized_last_name)

    normalized_email = _normalize_email(email)
    if normalized_email:
        existing = get_contact_by_email(normalized_email, db_session)
        if existing is not None:
            return existing, False

    normalized_principal = _strip_or_none(principal)
    if principal_contact_id is not None:
        normalized_principal = _linked_principal_name(
            db_session, None, principal_contact_id, new_link=True
        )

    normalized_owner_ids = _dedupe_uuid_list(owner_ids or [])
    normalized_status = _normalize_status(status)

    contact = CrmContact(
        first_name=normalized_first_name,
        last_name=normalized_last_name,
        email=normalized_email,
        phone=_strip_or_none(phone),
        title=_strip_or_none(title),
        organization_id=organization_id,
        source=source,
        status=normalized_status,
        category=_strip_or_none(category),
        party_affiliation=_strip_or_none(party_affiliation),
        us_state=_normalize_us_state(us_state),
        principal=normalized_principal,
        principal_contact_id=principal_contact_id,
        notes=_normalize_text(notes),
        linkedin_url=_strip_or_none(linkedin_url),
        location=_strip_or_none(location),
        profile_picture_file_id=profile_picture_file_id,
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
    field was actually modified. Renaming a contact also renames the
    principal text of the staffers linked to it.
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
        "party_affiliation",
        "us_state",
        "notes",
        "linkedin_url",
        "location",
        "profile_picture_file_id",
    }

    # Enforce the at-least-one-name invariant once, against the post-update
    # state. We compute the effective first/last names the contact will have
    # after applying this patch set (using patched values where present,
    # otherwise the contact's current values). This is order-independent and
    # covers clearing one or both names in a single patch.
    renamed = False
    if "first_name" in patches or "last_name" in patches:
        effective_first_name = (
            _strip_or_none(patches["first_name"])
            if "first_name" in patches
            else _strip_or_none(contact.first_name)
        )
        effective_last_name = (
            _strip_or_none(patches["last_name"])
            if "last_name" in patches
            else _strip_or_none(contact.last_name)
        )
        _require_at_least_one_name(effective_first_name, effective_last_name)
        renamed = " ".join(
            name for name in (effective_first_name, effective_last_name) if name
        ) != contact_full_name(contact)
        if renamed:
            # Linked staffers copy this name (synced below). Lock this contact
            # and them in id order, as the updated_at triggers do, so the sync
            # cannot deadlock with an interaction edit.
            db_session.execute(
                select(CrmContact.id)
                .where(
                    or_(
                        CrmContact.id == contact.id,
                        CrmContact.principal_contact_id == contact.id,
                    )
                )
                .order_by(CrmContact.id)
                .with_for_update(key_share=True)
            )

    changed = False
    if "principal" in patches or "principal_contact_id" in patches:
        changed = _apply_principal_patches(db_session, contact, patches)

    for key, value in patches.items():
        if key not in mutable_fields:
            continue

        if key == "first_name":
            normalized_first_name = _strip_or_none(value)
            if _strip_or_none(contact.first_name) != normalized_first_name:
                contact.first_name = normalized_first_name
                changed = True
            continue

        if key in {
            "last_name",
            "phone",
            "title",
            "linkedin_url",
            "location",
            "party_affiliation",
        }:
            normalized = _strip_or_none(value)
            current = getattr(contact, key)  # ods: ignore[getattr]
            if _strip_or_none(current) != normalized:
                setattr(contact, key, normalized)
                changed = True
            continue

        if key == "us_state":
            normalized = _normalize_us_state(value)
            if _normalize_us_state(contact.us_state) != normalized:
                contact.us_state = normalized
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

        if getattr(contact, key) != value:  # ods: ignore[getattr]
            setattr(contact, key, value)
            changed = True

    if renamed:
        db_session.execute(
            update(CrmContact)
            .where(CrmContact.principal_contact_id == contact.id)
            .values(principal=contact_full_name(contact))
        )

    if changed:
        db_session.flush()
        if commit:
            db_session.commit()
        db_session.refresh(contact)

    return contact, changed


def delete_contact(
    db_session: Session,
    *,
    contact: CrmContact,
    commit: bool = True,
) -> None:
    db_session.delete(contact)
    if commit:
        db_session.commit()
    else:
        db_session.flush()


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
    created_by: UUID | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    updated_after: datetime | None = None,
    updated_before: datetime | None = None,
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
        # Require ALL selected tags (intersection): one EXISTS per distinct tag.
        for tag_id in dict.fromkeys(tag_ids):
            stmt = stmt.where(
                select(CrmOrganization__Tag.organization_id)
                .where(
                    CrmOrganization__Tag.organization_id == CrmOrganization.id,
                    CrmOrganization__Tag.tag_id == tag_id,
                )
                .exists()
            )

    if created_by is not None:
        stmt = stmt.where(CrmOrganization.created_by == created_by)

    stmt = _apply_timestamp_filters(
        stmt,
        created_col=CrmOrganization.created_at,
        updated_col=CrmOrganization.updated_at,
        created_after=created_after,
        created_before=created_before,
        updated_after=updated_after,
        updated_before=updated_before,
    )

    total = db_session.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    order_clauses = _build_timestamp_order_clauses(
        CrmOrganization.created_at,
        CrmOrganization.updated_at,
        CrmOrganization.id,
        sort_by,
        sort_dir,
    )

    items = list(
        db_session.scalars(
            stmt.order_by(*order_clauses).offset(page_num * page_size).limit(page_size)
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
            current = getattr(organization, key)  # ods: ignore[getattr]
            if _strip_or_none(current) != normalized:
                setattr(organization, key, normalized)
                changed = True
            continue

        if key == "notes":
            normalized = _normalize_text(value)
            if _normalize_text(organization.notes) != normalized:
                organization.notes = normalized
                changed = True
            continue

        if getattr(organization, key) != value:  # ods: ignore[getattr]
            setattr(organization, key, value)
            changed = True

    if changed:
        db_session.flush()
        if commit:
            db_session.commit()
        db_session.refresh(organization)

    return organization, changed


def delete_organization(
    db_session: Session,
    *,
    organization: CrmOrganization,
    commit: bool = True,
) -> None:
    db_session.delete(organization)
    if commit:
        db_session.commit()
    else:
        db_session.flush()


def _interaction_ids_for_contacts(contact_condition: Any) -> list[Any]:
    """Interactions whose primary contact or a contact attendee matches the
    condition on a contact id column. Each branch has its own index."""
    return [
        select(CrmInteraction.id).where(contact_condition(CrmInteraction.contact_id)),
        select(CrmInteractionAttendee.interaction_id).where(
            contact_condition(CrmInteractionAttendee.contact_id)
        ),
    ]


def _office_contact_ids(normalized_principal: str) -> Any:
    """One office: the staffers whose principal matches, and the officials
    those staffers link to."""
    is_staffer = _principal_matches(normalized_principal)
    return union(
        select(CrmContact.id).where(is_staffer),
        select(CrmContact.principal_contact_id).where(
            is_staffer, CrmContact.principal_contact_id.is_not(None)
        ),
    )


def list_interactions(
    db_session: Session,
    *,
    page_num: int,
    page_size: int,
    contact_id: UUID | None = None,
    organization_id: UUID | None = None,
    include_contact_interactions: bool = False,
    principal: str | None = None,
    interaction_type: CrmInteractionType | None = None,
    logged_by: UUID | None = None,
) -> tuple[list[CrmInteraction], int]:
    """A contact's interactions include those where it is only an attendee.
    With include_contact_interactions, an organization's interactions also
    include those of its member contacts (as primary contact or attendee).
    With principal, only interactions with that office: any of its staffers
    or its linked official, as primary contact or attendee."""
    page_num, page_size = _normalize_page(page_num, page_size)

    stmt = select(CrmInteraction)
    # IN over a UNION of indexed lookups; an OR here scans every interaction.
    if contact_id:
        stmt = stmt.where(
            CrmInteraction.id.in_(
                union(*_interaction_ids_for_contacts(lambda col: col == contact_id))
            )
        )
    if organization_id:
        if include_contact_interactions:
            member_ids = select(CrmContact.id).where(
                CrmContact.organization_id == organization_id
            )
            stmt = stmt.where(
                CrmInteraction.id.in_(
                    union(
                        select(CrmInteraction.id).where(
                            CrmInteraction.organization_id == organization_id
                        ),
                        *_interaction_ids_for_contacts(lambda col: col.in_(member_ids)),
                    )
                )
            )
        else:
            stmt = stmt.where(CrmInteraction.organization_id == organization_id)
    normalized_principal = _normalize_lookup_name(principal)
    if normalized_principal:
        office_ids = _office_contact_ids(normalized_principal)
        stmt = stmt.where(
            CrmInteraction.id.in_(
                union(*_interaction_ids_for_contacts(lambda col: col.in_(office_ids)))
            )
        )
    if interaction_type is not None:
        stmt = stmt.where(CrmInteraction.type == interaction_type)
    if logged_by is not None:
        stmt = stmt.where(CrmInteraction.logged_by == logged_by)

    sort_expr = func.coalesce(CrmInteraction.occurred_at, CrmInteraction.created_at)
    total = db_session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = list(
        db_session.scalars(
            # The id tie-breaker keeps offset pagination stable on equal times.
            stmt.order_by(sort_expr.desc(), CrmInteraction.id.desc())
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


def update_interaction(
    db_session: Session,
    *,
    interaction: CrmInteraction,
    patches: dict,
    commit: bool = True,
) -> tuple[CrmInteraction, bool]:
    """Update a CrmInteraction with the given patches.

    Mutable fields: title, summary, type, occurred_at, contact_id, organization_id.
    Attendee replacement is handled separately (see replace_interaction_attendees).
    Returns (interaction, changed) where changed indicates whether any field was
    actually modified.
    """
    mutable_fields = {
        "title",
        "summary",
        "type",
        "occurred_at",
        "contact_id",
        "organization_id",
    }

    changed = False

    for key, value in patches.items():
        if key not in mutable_fields:
            continue

        if key == "title":
            normalized_title = _strip_or_none(value)
            if normalized_title is None:
                raise ValueError("Interaction title cannot be empty")
            if _strip_or_none(interaction.title) != normalized_title:
                interaction.title = normalized_title
                changed = True
            continue

        if key == "summary":
            normalized = _normalize_text(value)
            if _normalize_text(interaction.summary) != normalized:
                interaction.summary = normalized
                changed = True
            continue

        # type (CrmInteractionType), occurred_at (datetime|None),
        # contact_id / organization_id (UUID|None): direct assignment.
        if getattr(interaction, key) != value:  # ods: ignore[getattr]
            setattr(interaction, key, value)
            changed = True

    if changed:
        db_session.flush()
        if commit:
            db_session.commit()
        db_session.refresh(interaction)

    return interaction, changed


def replace_interaction_attendees(
    db_session: Session,
    *,
    interaction_id: UUID,
    attendees: list[tuple[UUID | None, UUID | None, CrmAttendeeRole]],
    commit: bool = True,
) -> bool:
    """Make the interaction's attendees exactly the given (user_id, contact_id,
    role) tuples. An empty list clears all attendees.

    Duplicate (user_id, contact_id) pairs collapse, preferring ORGANIZER. Only
    rows that differ are written, so an unchanged set fires no updated_at
    triggers. Returns True if any attendee row changed.
    """
    # Lock the interaction first, so concurrent replacements of the same
    # attendee list apply one after the other, not from the same stale read.
    db_session.execute(
        select(CrmInteraction.id)
        .where(CrmInteraction.id == interaction_id)
        .with_for_update(key_share=True)
    )
    desired: dict[tuple[UUID | None, UUID | None], CrmAttendeeRole] = {}
    for user_id, contact_id, role in attendees:
        key = (user_id, contact_id)
        existing_role = desired.get(key)
        if existing_role is None or (
            existing_role != CrmAttendeeRole.ORGANIZER
            and role == CrmAttendeeRole.ORGANIZER
        ):
            desired[key] = role

    current = {
        (attendee.user_id, attendee.contact_id): attendee
        for attendee in get_interaction_attendees(interaction_id, db_session)
    }

    changed = False
    for key, attendee in current.items():
        if key not in desired:
            db_session.delete(attendee)
            changed = True
    for (user_id, contact_id), role in desired.items():
        attendee = current.get((user_id, contact_id))
        if attendee is None:
            db_session.add(
                CrmInteractionAttendee(
                    interaction_id=interaction_id,
                    user_id=user_id,
                    contact_id=contact_id,
                    role=role,
                )
            )
            changed = True
        elif attendee.role != role:
            attendee.role = role
            changed = True

    if changed:
        db_session.flush()
        if commit:
            db_session.commit()
    return changed


def delete_interaction(
    db_session: Session,
    *,
    interaction: CrmInteraction,
    commit: bool = True,
) -> None:
    db_session.delete(interaction)
    if commit:
        db_session.commit()
    else:
        db_session.flush()


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


def get_organization_tags(organization_id: UUID, db_session: Session) -> list[CrmTag]:
    return list(
        db_session.scalars(
            select(CrmTag)
            .join(CrmOrganization__Tag, CrmOrganization__Tag.tag_id == CrmTag.id)
            .where(CrmOrganization__Tag.organization_id == organization_id)
            .order_by(CrmTag.name.asc())
        )
    )


def get_tags_by_ids(tag_ids: list[UUID], db_session: Session) -> dict[UUID, CrmTag]:
    if not tag_ids:
        return {}
    return {
        tag.id: tag
        for tag in db_session.scalars(select(CrmTag).where(CrmTag.id.in_(tag_ids)))
    }


def add_tag_to_contact(
    db_session: Session,
    *,
    contact_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> bool:
    """Returns False if the contact already had the tag."""
    inserted = db_session.execute(
        pg_insert(CrmContact__Tag)
        .values(contact_id=contact_id, tag_id=tag_id)
        .on_conflict_do_nothing()
        .returning(CrmContact__Tag.tag_id)
    ).first()
    if commit:
        db_session.commit()
    return inserted is not None


def remove_tag_from_contact(
    db_session: Session,
    *,
    contact_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> bool:
    """Returns False if the contact did not have the tag."""
    removed = db_session.execute(
        delete(CrmContact__Tag)
        .where(
            CrmContact__Tag.contact_id == contact_id,
            CrmContact__Tag.tag_id == tag_id,
        )
        .returning(CrmContact__Tag.tag_id)
    ).first()
    if commit:
        db_session.commit()
    return removed is not None


def add_tag_to_organization(
    db_session: Session,
    *,
    organization_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> bool:
    """Returns False if the organization already had the tag."""
    inserted = db_session.execute(
        pg_insert(CrmOrganization__Tag)
        .values(organization_id=organization_id, tag_id=tag_id)
        .on_conflict_do_nothing()
        .returning(CrmOrganization__Tag.tag_id)
    ).first()
    if commit:
        db_session.commit()
    return inserted is not None


def remove_tag_from_organization(
    db_session: Session,
    *,
    organization_id: UUID,
    tag_id: UUID,
    commit: bool = True,
) -> bool:
    """Returns False if the organization did not have the tag."""
    removed = db_session.execute(
        delete(CrmOrganization__Tag)
        .where(
            CrmOrganization__Tag.organization_id == organization_id,
            CrmOrganization__Tag.tag_id == tag_id,
        )
        .returning(CrmOrganization__Tag.tag_id)
    ).first()
    if commit:
        db_session.commit()
    return removed is not None


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

    requested_types = set(
        entity_types or ["contact", "organization", "interaction", "tag"]
    )

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

    count_query = text(f"SELECT COUNT(*) FROM ({union_sql}) AS crm_search")  # noqa: S608 -- union_sql built from static fragments; values are bound params
    total = db_session.execute(
        count_query, {"query": query, "escaped_like_query": escaped_like_query}
    ).scalar_one()

    rows = db_session.execute(
        text(
            f"""
            SELECT entity_type, entity_id, primary_text, secondary_text, sort_at, rank
            FROM ({union_sql}) AS crm_search
            ORDER BY rank DESC, sort_at DESC NULLS LAST, primary_text ASC,
                entity_type ASC, entity_id ASC
            OFFSET :offset
            LIMIT :limit
            """  # noqa: S608 -- union_sql built from static fragments; values are bound params
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
                str(row["secondary_text"])
                if row["secondary_text"] is not None
                else None
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


def get_user_names_and_emails(
    user_ids: set[UUID], db_session: Session
) -> dict[UUID, tuple[str | None, str]]:
    if not user_ids:
        return {}
    table = User.__table__
    rows = db_session.execute(
        select(table.c.id, table.c.personal_name, table.c.email).where(
            table.c.id.in_(user_ids)
        )
    )
    return {user_id: (personal_name, email) for user_id, personal_name, email in rows}


def get_contact_names(contact_ids: set[UUID], db_session: Session) -> dict[UUID, str]:
    """Full name, else email, for each contact."""
    if not contact_ids:
        return {}
    rows = db_session.execute(
        select(
            CrmContact.id,
            CrmContact.first_name,
            CrmContact.last_name,
            CrmContact.email,
        ).where(CrmContact.id.in_(contact_ids))
    )
    return {
        contact_id: " ".join(
            part.strip() for part in (first, last) if part and part.strip()
        )
        or (email or "")
        for contact_id, first, last, email in rows
    }


def get_organization_names(
    organization_ids: set[UUID], db_session: Session
) -> dict[UUID, str]:
    if not organization_ids:
        return {}
    rows = db_session.execute(
        select(CrmOrganization.id, CrmOrganization.name).where(
            CrmOrganization.id.in_(organization_ids)
        )
    )
    return dict(rows.tuples())


def get_existing_user_ids(user_ids: list[UUID], db_session: Session) -> set[UUID]:
    if not user_ids:
        return set()
    id_col = User.__table__.c.id
    return set(db_session.scalars(select(id_col).where(id_col.in_(user_ids))))


def find_assignable_users_by_email(
    emails: list[str], db_session: Session
) -> dict[str, list[User]]:
    """Exact, case-insensitive email match over the users the CRM owner picker
    shows (no bots, API-key users, external or system users). Keys are
    lower-cased emails; more than one user per key means the match is ambiguous.
    """
    lowered = {email.strip().lower() for email in emails if email.strip()}
    if not lowered:
        return {}
    email_col = User.__table__.c.email
    users = db_session.scalars(
        select(User).where(
            func.lower(email_col).in_(lowered),
            expression.not_(email_col.endswith(DANSWER_API_KEY_DUMMY_EMAIL_DOMAIN)),
            email_col != ANONYMOUS_USER_EMAIL,
            email_col != NO_AUTH_PLACEHOLDER_USER_EMAIL,
            User.account_type.not_in([AccountType.BOT, AccountType.EXT_PERM_USER]),
        )
    ).unique()
    matches: dict[str, list[User]] = {}
    for user in users:
        matches.setdefault(user.email.lower(), []).append(user)
    return matches


def export_all_organizations(db_session: Session) -> list[dict]:
    """Export all organizations with tags for CSV."""
    orgs = list(
        db_session.scalars(select(CrmOrganization).order_by(CrmOrganization.name.asc()))
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
        creator_emails = dict(user_rows)

    results: list[dict] = [
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
        for org in orgs
    ]
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
        org_names = dict(org_rows)

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
        creator_emails = dict(user_rows)

    results: list[dict] = [
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
            "party_affiliation": _strip_or_none(c.party_affiliation) or "",
            "us_state": _normalize_us_state(c.us_state) or "",
            "principal": _strip_or_none(c.principal) or "",
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
        for c in contacts
    ]
    return results


def export_all_interactions(db_session: Session) -> list[dict]:
    """Export all interactions with contact email and org name for CSV."""
    sort_expr = func.coalesce(CrmInteraction.occurred_at, CrmInteraction.created_at)
    interactions = list(
        db_session.scalars(select(CrmInteraction).order_by(sort_expr.desc()))
    )
    if not interactions:
        return []

    # Bulk-fetch contact emails
    contact_ids = list({i.contact_id for i in interactions if i.contact_id is not None})
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
        org_names = dict(org_rows)

    # Bulk-fetch logger emails
    logger_ids = list({i.logged_by for i in interactions if i.logged_by is not None})
    logger_emails: dict[UUID, str] = {}
    if logger_ids:
        user_rows = db_session.execute(
            select(User.id, User.email).where(User.id.in_(logger_ids))
        ).all()
        logger_emails = dict(user_rows)

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
    attendee_user_ids = list({a.user_id for a in attendees if a.user_id is not None})
    attendee_user_emails: dict[UUID, str] = {}
    if attendee_user_ids:
        rows = db_session.execute(
            select(User.id, User.email).where(User.id.in_(attendee_user_ids))
        ).all()
        attendee_user_emails = dict(rows)

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
        attendee_contact_emails = dict(rows)

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
                "occurred_at": str(i.occurred_at) if i.occurred_at is not None else "",
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
    rows = db_session.execute(select(CrmOrganization.id, CrmOrganization.name)).all()
    result: dict[str, UUID] = {}
    for oid, name in rows:
        normalized_name = _normalize_lookup_name(name)
        if normalized_name is not None:
            result[normalized_name] = oid
    return result


def build_contact_email_lookup(db_session: Session) -> dict[str, UUID]:
    """Build {lowercase_email: contact_id} lookup dict."""
    rows = db_session.execute(
        select(CrmContact.id, CrmContact.email).where(CrmContact.email.isnot(None))
    ).all()
    result: dict[str, UUID] = {}
    for cid, email in rows:
        normalized_email = _normalize_email(email)
        if normalized_email is not None:
            result[normalized_email] = cid
    return result


def build_user_email_lookup(db_session: Session) -> dict[str, UUID]:
    """Build {lowercase_email: user_id} lookup dict for resolving owner_emails."""
    rows = db_session.execute(select(User.id, User.email)).all()
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
        tag, _created = create_tag(db_session, name=name, color=None, commit=False)
        result[name.lower()] = tag.id
    db_session.flush()
    if commit:
        db_session.commit()
    return result
