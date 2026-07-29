from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.constants import FileOrigin
from onyx.db.crm import (
    get_allowed_contact_stages,
    get_contact_by_id,
    get_contact_category_options,
    get_contact_owner_ids,
    get_contact_tags,
    get_interaction_attendees,
    get_interaction_by_id,
    get_organization_by_id,
    get_organization_tags,
    replace_interaction_attendees,
    update_contact,
    update_interaction,
    update_organization,
)
from onyx.db.enums import (
    CrmAttendeeRole,
    CrmContactSource,
    CrmInteractionType,
    CrmOrganizationType,
)
from onyx.db.models import User
from onyx.file_store.utils import save_file_from_url
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CrmUpdateToolDelta,
    CrmUpdateToolStart,
    Packet,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolResponse
from onyx.tools.tool_implementations.crm.attendee_resolution import resolve_attendees
from onyx.tools.tool_implementations.crm.models import (
    as_llm_json,
    compact_tool_payload_for_model,
    is_crm_schema_available,
    parse_datetime_maybe,
    parse_enum_maybe,
    parse_stage_maybe,
    parse_uuid_maybe,
    serialize_contact,
    serialize_interaction,
    serialize_organization,
)
from onyx.utils.logger import setup_logger

CRM_UPDATE_ENTITY_TYPES = {"contact", "organization", "interaction"}
logger = setup_logger()


class CrmUpdateTool(Tool[None]):
    NAME = "crm_update"
    DISPLAY_NAME = "CRM Update"
    DESCRIPTION = (
        "Update fields on an existing CRM contact, organization, or interaction. Requires the "
        "entity's UUID (from a prior search, list, or create). Only include fields you want to "
        "change in the updates object — omitted fields are left unchanged. Use this to fix info, "
        "change status, reassign ownership, link a contact to an organization, or correct an "
        "interaction's details (including its occurred_at time and attendees)."
    )

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
        user_id: str | None = None,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._user_id = user_id
        self._session_factory = sessionmaker(bind=db_session.get_bind())
        self._stage_options = get_allowed_contact_stages(db_session)
        self._category_options = get_contact_category_options(db_session)

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        return is_crm_schema_available(db_session)

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "enum": sorted(list(CRM_UPDATE_ENTITY_TYPES)),
                            "description": "Whether to update a 'contact', 'organization', or 'interaction'.",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "UUID of the CRM entity to update.",
                        },
                        "updates": {
                            "type": "object",
                            "description": (
                                "Fields to update. Only include fields you want to change. "
                                "For contacts: first_name, last_name, email, phone, title (job title), "
                                "organization_id, owner_ids, source (manual|import|referral|inbound|other), "
                                "status (workspace-defined contact stages), "
                                "category (must be one of the workspace-defined category options), "
                                "party_affiliation, us_state (2-letter US state abbreviation), "
                                "principal (for staffers, the name of the principal they work for), "
                                "notes, linkedin_url, location, "
                                "profile_picture_url (remote image URL or null to clear). "
                                "A contact must always keep at least a first_name or a last_name. "
                                "For organizations: name, website, type (customer|prospect|partner|vendor|other), "
                                "sector, location, size, notes. "
                                "For interactions: title, summary, type (note|call|email|meeting|event), "
                                "occurred_at (ISO datetime, or null to clear), contact_id, organization_id, "
                                "attendees (full replacement: array of {email|name|contact_id|user_id, role}; "
                                "omit to leave attendees unchanged, [] to remove all)."
                            ),
                        },
                    },
                    "required": ["entity_type", "entity_id", "updates"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmUpdateToolStart()))

    def _normalize_contact_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        normalized_updates = dict(updates)
        if "profile_picture_url" in normalized_updates:
            profile_picture_url = normalized_updates.pop("profile_picture_url")
            if profile_picture_url is None:
                normalized_updates["profile_picture_file_id"] = None
            elif isinstance(profile_picture_url, str):
                normalized_url = profile_picture_url.strip()
                if not normalized_url:
                    normalized_updates["profile_picture_file_id"] = None
                else:
                    try:
                        normalized_updates["profile_picture_file_id"] = (
                            save_file_from_url(
                                normalized_url,
                                display_name="crm_profile_picture",
                                file_origin=FileOrigin.CRM_UPLOAD,
                                require_image=True,
                            )
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to download CRM contact profile picture during update: %s",
                            e,
                        )
                        raise ToolCallException(
                            message=(
                                "Failed to download CRM contact profile picture "
                                f"from {normalized_url}: {e}"
                            ),
                            llm_facing_message=(
                                "I could not download the image from "
                                f"{normalized_url!r}, so the contact was not updated "
                                "with a new profile picture. Use a reachable image URL."
                            ),
                        ) from e
            else:
                raise ToolCallException(
                    message=f"Invalid profile_picture_url payload type: {type(profile_picture_url)}",
                    llm_facing_message="'updates.profile_picture_url' must be a string URL or null.",
                )

        if "source" in normalized_updates:
            normalized_updates["source"] = parse_enum_maybe(
                CrmContactSource,
                normalized_updates.get("source"),
                "updates.source",
            )
        if "status" in normalized_updates:
            normalized_updates["status"] = parse_stage_maybe(
                normalized_updates.get("status"),
                allowed_stages=self._stage_options,
                field_name="updates.status",
            )
        if "category" in normalized_updates and self._category_options:
            category_value = normalized_updates.get("category")
            if isinstance(category_value, str):
                category_value = category_value.strip()
                normalized_updates["category"] = category_value
            if (
                category_value is not None
                and category_value not in self._category_options
            ):
                raise ToolCallException(
                    message=f"Invalid category value in crm_update: {category_value}",
                    llm_facing_message=(
                        "'updates.category' must be one of: "
                        f"{', '.join(self._category_options)}."
                    ),
                )
        if "organization_id" in normalized_updates:
            normalized_updates["organization_id"] = parse_uuid_maybe(
                normalized_updates.get("organization_id"),
                "updates.organization_id",
            )
        if "owner_ids" in normalized_updates:
            owner_ids_raw = normalized_updates.get("owner_ids")
            if owner_ids_raw is None:
                normalized_updates["owner_ids"] = []
            elif isinstance(owner_ids_raw, list):
                owner_ids: list[UUID] = []
                seen_owner_ids: set[UUID] = set()
                for owner_id_raw in owner_ids_raw:
                    parsed_owner_id = parse_uuid_maybe(
                        owner_id_raw, "updates.owner_ids[]"
                    )
                    if parsed_owner_id is None or parsed_owner_id in seen_owner_ids:
                        continue
                    seen_owner_ids.add(parsed_owner_id)
                    owner_ids.append(parsed_owner_id)
                normalized_updates["owner_ids"] = owner_ids
            else:
                raise ToolCallException(
                    message=f"Invalid owner_ids payload type: {type(owner_ids_raw)}",
                    llm_facing_message="'updates.owner_ids' must be an array of UUID strings.",
                )

        return normalized_updates

    def _normalize_organization_updates(
        self, updates: dict[str, Any]
    ) -> dict[str, Any]:
        normalized_updates = dict(updates)
        if "type" in normalized_updates:
            normalized_updates["type"] = parse_enum_maybe(
                CrmOrganizationType,
                normalized_updates.get("type"),
                "updates.type",
            )
        return normalized_updates

    def _normalize_interaction_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Normalize interaction column patches (excludes 'attendees').

        Returns a dict of column patches suitable for update_interaction. The
        'attendees' key is intentionally left untouched here and handled
        separately by the caller (full-replace semantics).
        """
        normalized_updates = dict(updates)

        if "type" in normalized_updates:
            interaction_type = parse_enum_maybe(
                CrmInteractionType,
                normalized_updates.get("type"),
                "updates.type",
            )
            if interaction_type is None:
                raise ToolCallException(
                    message="Missing/invalid interaction type in crm_update",
                    llm_facing_message=(
                        "'updates.type' must be one of: "
                        f"{', '.join(member.value for member in CrmInteractionType)}."
                    ),
                )
            normalized_updates["type"] = interaction_type

        if "occurred_at" in normalized_updates:
            normalized_updates["occurred_at"] = parse_datetime_maybe(
                normalized_updates.get("occurred_at"),
                "updates.occurred_at",
            )

        if "contact_id" in normalized_updates:
            normalized_updates["contact_id"] = parse_uuid_maybe(
                normalized_updates.get("contact_id"),
                "updates.contact_id",
            )

        if "organization_id" in normalized_updates:
            normalized_updates["organization_id"] = parse_uuid_maybe(
                normalized_updates.get("organization_id"),
                "updates.organization_id",
            )

        if "title" in normalized_updates:
            title_value = normalized_updates.get("title")
            if not isinstance(title_value, str) or not title_value.strip():
                raise ToolCallException(
                    message="Empty interaction title in crm_update",
                    llm_facing_message="'updates.title' cannot be empty.",
                )

        if "summary" in normalized_updates:
            summary_value = normalized_updates.get("summary")
            if summary_value is not None and not isinstance(summary_value, str):
                raise ToolCallException(
                    message=f"Invalid summary payload type: {type(summary_value)}",
                    llm_facing_message="'updates.summary' must be a string or null.",
                )

        return normalized_updates

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        entity_type_raw = llm_kwargs.get("entity_type")
        if not isinstance(entity_type_raw, str):
            raise ToolCallException(
                message=f"Missing/invalid entity_type in {self.name}",
                llm_facing_message="'entity_type' must be one of: contact, organization, interaction.",
            )

        entity_type = entity_type_raw.strip().lower()
        if entity_type not in CRM_UPDATE_ENTITY_TYPES:
            raise ToolCallException(
                message=f"Unsupported entity_type in {self.name}: {entity_type}",
                llm_facing_message="'entity_type' must be one of: contact, organization, interaction.",
            )

        entity_id = parse_uuid_maybe(llm_kwargs.get("entity_id"), "entity_id")
        if not entity_id:
            raise ToolCallException(
                message=f"Missing/invalid entity_id in {self.name}",
                llm_facing_message="'entity_id' must be a valid UUID.",
            )

        updates_raw = llm_kwargs.get("updates")
        if not isinstance(updates_raw, dict):
            raise ToolCallException(
                message=f"Missing updates object in {self.name}",
                llm_facing_message="'updates' must be an object with fields to update.",
            )

        with self._session_factory() as db_session:
            try:
                if entity_type == "contact":
                    contact = get_contact_by_id(entity_id, db_session)
                    if contact is None:
                        raise ToolCallException(
                            message=f"Contact not found: {entity_id}",
                            llm_facing_message="Could not find the specified contact.",
                        )

                    updates = self._normalize_contact_updates(updates_raw)
                    if updates.get("organization_id") is not None:
                        organization = get_organization_by_id(
                            updates["organization_id"], db_session
                        )
                        if organization is None:
                            raise ToolCallException(
                                message=f"Organization not found: {updates['organization_id']}",
                                llm_facing_message="Could not find the provided organization_id.",
                            )
                    if "owner_ids" in updates:
                        for owner_id in updates["owner_ids"]:
                            if db_session.get(User, owner_id) is not None:
                                continue
                            raise ToolCallException(
                                message=f"Owner user not found: {owner_id}",
                                llm_facing_message="Could not find one of the provided updates.owner_ids users.",
                            )

                    updated_contact, _ = update_contact(
                        db_session=db_session,
                        contact=contact,
                        patches=updates,
                    )
                    tags = get_contact_tags(updated_contact.id, db_session)
                    owner_ids = get_contact_owner_ids(updated_contact.id, db_session)
                    payload = {
                        "status": "updated",
                        "entity_type": "contact",
                        "contact": serialize_contact(
                            updated_contact,
                            owner_ids=owner_ids,
                            tags=tags,
                        ),
                    }
                elif entity_type == "organization":
                    organization = get_organization_by_id(entity_id, db_session)
                    if organization is None:
                        raise ToolCallException(
                            message=f"Organization not found: {entity_id}",
                            llm_facing_message="Could not find the specified organization.",
                        )

                    updates = self._normalize_organization_updates(updates_raw)
                    updated_organization, _ = update_organization(
                        db_session=db_session,
                        organization=organization,
                        patches=updates,
                    )
                    tags = get_organization_tags(updated_organization.id, db_session)
                    payload = {
                        "status": "updated",
                        "entity_type": "organization",
                        "organization": serialize_organization(
                            updated_organization,
                            tags=tags,
                        ),
                    }
                else:
                    interaction = get_interaction_by_id(entity_id, db_session)
                    if interaction is None:
                        raise ToolCallException(
                            message=f"Interaction not found: {entity_id}",
                            llm_facing_message="Could not find the specified interaction.",
                        )

                    # Pull attendees out of the column patches; they are
                    # full-replaced separately and only when the key is present.
                    attendees_present = "attendees" in updates_raw
                    attendees_raw = updates_raw.get("attendees")

                    updates = self._normalize_interaction_updates(updates_raw)
                    updates.pop("attendees", None)

                    if updates.get("contact_id") is not None:
                        if get_contact_by_id(updates["contact_id"], db_session) is None:
                            raise ToolCallException(
                                message=f"Contact not found: {updates['contact_id']}",
                                llm_facing_message="Could not find the provided contact_id.",
                            )
                    if updates.get("organization_id") is not None:
                        if (
                            get_organization_by_id(
                                updates["organization_id"], db_session
                            )
                            is None
                        ):
                            raise ToolCallException(
                                message=f"Organization not found: {updates['organization_id']}",
                                llm_facing_message="Could not find the provided organization_id.",
                            )

                    # Validate and resolve attendees BEFORE applying any column
                    # patches so a failure here leaves the interaction untouched.
                    attendee_resolution_details: list[dict[str, Any]] = []
                    attendee_tuples: list[
                        tuple[UUID | None, UUID | None, CrmAttendeeRole]
                    ] = []
                    if attendees_present:
                        if attendees_raw is None:
                            attendees_to_resolve: list[Any] = []
                        elif isinstance(attendees_raw, list):
                            attendees_to_resolve = attendees_raw
                        else:
                            raise ToolCallException(
                                message=(
                                    "Invalid attendees payload in crm_update: "
                                    f"{type(attendees_raw)}"
                                ),
                                llm_facing_message="'updates.attendees' must be an array.",
                            )

                        (
                            resolved_attendees,
                            unresolved_attendees,
                            attendee_resolution_details,
                        ) = resolve_attendees(
                            db_session=db_session,
                            attendees_to_resolve=attendees_to_resolve,
                        )

                        if unresolved_attendees:
                            # 'attendees' is a full replacement; replacing with
                            # only the resolved subset would silently drop the
                            # unresolved ones (or wipe all existing attendees if
                            # nothing resolved). Refuse the whole update instead.
                            unresolved_summary = json.dumps(
                                unresolved_attendees, default=str
                            )
                            raise ToolCallException(
                                message=(
                                    "Unresolved attendees in crm_update: "
                                    f"{unresolved_summary}"
                                ),
                                llm_facing_message=(
                                    "The interaction was NOT updated because some "
                                    "attendees could not be resolved and "
                                    "'updates.attendees' replaces the full attendee "
                                    "list. Unresolved attendees (with candidate "
                                    f"matches): {unresolved_summary}. Retry with "
                                    "exact contact_id/user_id values or corrected "
                                    "emails/names, or omit 'attendees' to leave the "
                                    "attendee list unchanged."
                                ),
                            )

                        attendee_tuples = [
                            (
                                attendee["user_id"],
                                attendee["contact_id"],
                                attendee["role"],
                            )
                            for attendee in resolved_attendees
                        ]

                    updated_interaction, _ = update_interaction(
                        db_session=db_session,
                        interaction=interaction,
                        patches=updates,
                        commit=False,
                    )

                    if attendees_present:
                        replace_interaction_attendees(
                            db_session=db_session,
                            interaction_id=updated_interaction.id,
                            attendees=attendee_tuples,
                            commit=False,
                        )

                    db_session.commit()

                    attendees = get_interaction_attendees(
                        updated_interaction.id, db_session
                    )
                    payload = {
                        "status": "updated",
                        "entity_type": "interaction",
                        "interaction": serialize_interaction(
                            updated_interaction,
                            attendees=attendees,
                        ),
                    }
                    if attendee_resolution_details:
                        payload["attendee_resolution"] = attendee_resolution_details
            except IntegrityError:
                raise ToolCallException(
                    message="Unique constraint violation while updating CRM entity",
                    llm_facing_message="Update failed due to duplicate unique field value.",
                )
            except ValueError as e:
                raise ToolCallException(
                    message=f"CRM update validation failed: {e}",
                    llm_facing_message=str(e),
                )

        compact_payload = compact_tool_payload_for_model(payload)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CrmUpdateToolDelta(payload=compact_payload),
            )
        )

        rich_response = json.dumps(payload, default=str)
        llm_response = as_llm_json(compact_payload, already_compacted=True)
        return ToolResponse(
            rich_response=rich_response,
            llm_facing_response=llm_response,
        )
