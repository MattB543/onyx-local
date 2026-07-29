from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.crm import (
    find_contacts_for_attendee_resolution,
    find_users_for_attendee_resolution,
    get_contact_by_id,
)
from onyx.db.enums import CrmAttendeeRole
from onyx.db.models import User
from onyx.tools.tool_implementations.crm.models import (
    contact_full_name,
    parse_enum_maybe,
    parse_uuid_maybe,
)


def serialize_contact_candidate(contact: Any) -> dict[str, Any]:
    return {
        "entity_type": "contact",
        "id": str(contact.id),
        "label": contact_full_name(contact) or contact.email or str(contact.id),
        "email": contact.email,
    }


def serialize_user_candidate(user: Any) -> dict[str, Any]:
    return {
        "entity_type": "user",
        "id": str(user.id),
        "label": (user.personal_name or user.email or str(user.id)),
        "email": user.email,
    }


def resolve_attendee_token(
    token: str,
    db_session: Session,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    """Resolve a free-text attendee token (email or name) to a contact or user.

    Returns (resolved, candidates, reason). When resolved is a dict it contains
    'user_id' and 'contact_id' (exactly one set). When resolution is ambiguous or
    fails, resolved is None and candidates/reason describe the failure.
    """
    normalized = token.strip()
    if not normalized:
        return None, [], "empty"

    normalized_lower = normalized.lower()
    contacts = find_contacts_for_attendee_resolution(
        db_session=db_session,
        token=normalized,
        max_results=5,
    )
    users = find_users_for_attendee_resolution(
        db_session=db_session,
        token=normalized,
        max_results=5,
    )

    # Priority 1: exact contact email
    exact_contact_email = next(
        (
            contact
            for contact in contacts
            if contact.email and contact.email.lower() == normalized_lower
        ),
        None,
    )
    if exact_contact_email:
        return (
            {
                "user_id": None,
                "contact_id": exact_contact_email.id,
            },
            [],
            None,
        )

    # Priority 2: exact user email
    exact_user_email = next(
        (
            user
            for user in users
            if user.email and user.email.lower() == normalized_lower
        ),
        None,
    )
    if exact_user_email:
        return (
            {
                "user_id": exact_user_email.id,
                "contact_id": None,
            },
            [],
            None,
        )

    # Priority 3: exact contact full-name
    exact_contact_name_matches = [
        contact
        for contact in contacts
        if contact_full_name(contact).lower() == normalized_lower
    ]
    if len(exact_contact_name_matches) == 1:
        return (
            {
                "user_id": None,
                "contact_id": exact_contact_name_matches[0].id,
            },
            [],
            None,
        )
    if len(exact_contact_name_matches) > 1:
        return (
            None,
            [
                serialize_contact_candidate(contact)
                for contact in exact_contact_name_matches
            ],
            "ambiguous_exact_contact_name",
        )

    # Priority 4: fuzzy contact name
    fuzzy_contact_matches = []
    for contact in contacts:
        candidate_name = contact_full_name(contact).lower()
        candidate_email = (contact.email or "").lower()
        if normalized_lower in candidate_name or normalized_lower in candidate_email:
            fuzzy_contact_matches.append(contact)

    if len(fuzzy_contact_matches) == 1:
        return (
            {
                "user_id": None,
                "contact_id": fuzzy_contact_matches[0].id,
            },
            [],
            None,
        )
    if len(fuzzy_contact_matches) > 1:
        return (
            None,
            [serialize_contact_candidate(contact) for contact in fuzzy_contact_matches],
            "ambiguous_fuzzy_contact_name",
        )

    # Priority 5: fuzzy user display/email
    fuzzy_user_matches = []
    for user in users:
        candidate_name = (user.personal_name or "").lower()
        candidate_email = (user.email or "").lower()
        if normalized_lower in candidate_name or normalized_lower in candidate_email:
            fuzzy_user_matches.append(user)

    if len(fuzzy_user_matches) == 1:
        return (
            {
                "user_id": fuzzy_user_matches[0].id,
                "contact_id": None,
            },
            [],
            None,
        )
    if len(fuzzy_user_matches) > 1:
        return (
            None,
            [serialize_user_candidate(user) for user in fuzzy_user_matches],
            "ambiguous_fuzzy_user_name",
        )

    return None, [], "not_found"


def resolve_attendees(
    db_session: Session,
    attendees_to_resolve: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve a list of attendee inputs to contact/user references.

    Each input item may be a free-text string, or a dict with any of
    email/name/contact_id/user_id/role. Returns three lists:
      - resolved_attendees: [{user_id, contact_id, role}]
      - needs_confirmation: items that could not be resolved (with candidates)
      - resolution_details: how each resolved item matched (for reporting)
    """
    resolved_attendees: list[dict[str, Any]] = []
    needs_confirmation: list[dict[str, Any]] = []
    resolution_details: list[dict[str, Any]] = []

    for attendee in attendees_to_resolve:
        role = CrmAttendeeRole.ATTENDEE
        token_for_resolution: str | None = None
        user_id: UUID | None = None
        attendee_contact_id: UUID | None = None

        if isinstance(attendee, str):
            token_for_resolution = attendee
        elif isinstance(attendee, dict):
            role_raw = attendee.get("role")
            parsed_role = parse_enum_maybe(
                CrmAttendeeRole, role_raw, "attendees[].role"
            )
            if isinstance(parsed_role, CrmAttendeeRole):
                role = parsed_role

            user_id = parse_uuid_maybe(attendee.get("user_id"), "attendees[].user_id")
            attendee_contact_id = parse_uuid_maybe(
                attendee.get("contact_id"),
                "attendees[].contact_id",
            )

            if user_id and attendee_contact_id:
                needs_confirmation.append(
                    {
                        "input": attendee,
                        "reason": "invalid_both_user_and_contact_provided",
                        "candidates": [],
                    }
                )
                continue

            token_for_resolution = (
                attendee.get("email")
                or attendee.get("name")
                or attendee.get("id")
                or attendee.get("token")
            )
        else:
            needs_confirmation.append(
                {
                    "input": str(attendee),
                    "reason": "invalid_attendee_item_type",
                    "candidates": [],
                }
            )
            continue

        if user_id:
            user = db_session.get(User, user_id)
            if user is None:
                needs_confirmation.append(
                    {
                        "input": str(user_id),
                        "reason": "user_not_found",
                        "candidates": [],
                    }
                )
                continue
            resolved_attendees.append(
                {
                    "user_id": user.id,
                    "contact_id": None,
                    "role": role,
                }
            )
            resolution_details.append(
                {
                    "input": str(user_id),
                    "matched_type": "user",
                    "matched_label": user.personal_name or user.email or str(user.id),
                    "confidence": "exact_id",
                }
            )
            continue

        if attendee_contact_id:
            attendee_contact = get_contact_by_id(attendee_contact_id, db_session)
            if attendee_contact is None:
                needs_confirmation.append(
                    {
                        "input": str(attendee_contact_id),
                        "reason": "contact_not_found",
                        "candidates": [],
                    }
                )
                continue
            resolved_attendees.append(
                {
                    "user_id": None,
                    "contact_id": attendee_contact.id,
                    "role": role,
                }
            )
            resolution_details.append(
                {
                    "input": str(attendee_contact_id),
                    "matched_type": "contact",
                    "matched_label": contact_full_name(attendee_contact)
                    or attendee_contact.email
                    or str(attendee_contact.id),
                    "confidence": "exact_id",
                }
            )
            continue

        if token_for_resolution and isinstance(token_for_resolution, str):
            resolved, candidates, reason = resolve_attendee_token(
                token=token_for_resolution,
                db_session=db_session,
            )
            if resolved:
                resolved_attendees.append(
                    {
                        "user_id": resolved["user_id"],
                        "contact_id": resolved["contact_id"],
                        "role": role,
                    }
                )
                # Determine matched label for resolution details
                if resolved["contact_id"]:
                    matched_contact = get_contact_by_id(
                        resolved["contact_id"], db_session
                    )
                    matched_label = (
                        contact_full_name(matched_contact)
                        if matched_contact
                        else str(resolved["contact_id"])
                    )
                    matched_type = "contact"
                else:
                    matched_user = db_session.get(User, resolved["user_id"])
                    matched_label = (
                        (
                            matched_user.personal_name
                            or matched_user.email
                            or str(matched_user.id)
                        )
                        if matched_user
                        else str(resolved["user_id"])
                    )
                    matched_type = "user"

                # Map None reason to a confidence level
                confidence = "fuzzy_match"
                if "@" in token_for_resolution:
                    confidence = "exact_email"
                elif token_for_resolution.lower() == matched_label.lower():
                    confidence = "exact_name"

                resolution_details.append(
                    {
                        "input": token_for_resolution,
                        "matched_type": matched_type,
                        "matched_label": matched_label,
                        "confidence": confidence,
                    }
                )
            else:
                needs_confirmation.append(
                    {
                        "input": token_for_resolution,
                        "reason": reason or "unresolved",
                        "candidates": candidates,
                    }
                )
        else:
            needs_confirmation.append(
                {
                    "input": attendee,
                    "reason": "missing_attendee_identifier",
                    "candidates": [],
                }
            )

    return resolved_attendees, needs_confirmation, resolution_details
