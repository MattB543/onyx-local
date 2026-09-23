from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.constants import FileOrigin
from onyx.db.crm import (
    add_tag_to_contact,
    add_tag_to_organization,
    get_allowed_contact_stages,
    get_contact_by_id,
    get_contact_category_options,
    get_interaction_by_id,
    get_organization_by_id,
    get_organization_tags,
    remove_tag_from_contact,
    remove_tag_from_organization,
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
from onyx.db.models import CrmContact, CrmOrganization, CrmTag
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
    crm_tool_response,
    is_crm_schema_available,
    parse_datetime_maybe,
    parse_enum_maybe,
    parse_stage_maybe,
    parse_uuid_maybe,
    serialize_contacts,
    serialize_interactions,
    serialize_organization,
)
from onyx.tools.tool_implementations.crm.validation import (
    crm_write_errors,
    parse_entity_type,
    parse_uuid_list,
    reject_unknown_keys,
    require_tags,
    resolve_owner_ids,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

TAG_CHANGE_FIELDS = ("add_tag_ids", "remove_tag_ids")
CONTACT_UPDATE_FIELDS = (
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
    "principal",
    "notes",
    "linkedin_url",
    "location",
    "profile_picture_url",
    *TAG_CHANGE_FIELDS,
)
ORGANIZATION_UPDATE_FIELDS = (
    "name",
    "website",
    "type",
    "sector",
    "location",
    "size",
    "notes",
    *TAG_CHANGE_FIELDS,
)
INTERACTION_UPDATE_FIELDS = (
    "title",
    "summary",
    "type",
    "occurred_at",
    "contact_id",
    "organization_id",
    "attendees",
)
UPDATE_FIELDS_BY_ENTITY_TYPE = {
    "contact": CONTACT_UPDATE_FIELDS,
    "organization": ORGANIZATION_UPDATE_FIELDS,
    "interaction": INTERACTION_UPDATE_FIELDS,
}
CRM_UPDATE_ENTITY_TYPES = set(UPDATE_FIELDS_BY_ENTITY_TYPE)
TOP_LEVEL_FIELDS = ("entity_type", "entity_id", "updates")


def _tag_refs(tags: list[CrmTag]) -> list[dict[str, str]]:
    return [{"id": str(tag.id), "name": tag.name} for tag in tags]


class CrmUpdateTool(Tool[None]):
    NAME = "crm_update"
    DISPLAY_NAME = "CRM Update"
    DESCRIPTION = (
        "Change an existing contact, organization, or interaction by UUID. Send only "
        "fields to change; use add_tag_ids / remove_tag_ids for tags. Unknown fields "
        "are rejected. Returns 'updated' (with tag changes) or 'no_changes'."
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
        tag_ids_schema = {"type": "array", "items": {"type": "string"}}
        category_schema: dict[str, Any] = {
            "type": "string",
            "description": "Contact category.",
        }
        if self._category_options:
            category_schema["enum"] = self._category_options
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
                            "enum": sorted(CRM_UPDATE_ENTITY_TYPES),
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "UUID of the record to change.",
                        },
                        "updates": {
                            "type": "object",
                            "description": (
                                "Only the fields to change; null clears an "
                                "optional field. "
                                + " ".join(
                                    f"{entity_type.capitalize()} fields: "
                                    f"{', '.join(fields)}."
                                    for entity_type, fields in UPDATE_FIELDS_BY_ENTITY_TYPE.items()
                                )
                            ),
                            "properties": {
                                "first_name": {"type": "string"},
                                "last_name": {
                                    "type": "string",
                                    "description": (
                                        "A contact must keep a first_name or a last_name."
                                    ),
                                },
                                "email": {"type": "string"},
                                "phone": {"type": "string"},
                                "title": {
                                    "type": "string",
                                    "description": (
                                        "Contact: job title. Interaction: title "
                                        "(cannot be empty)."
                                    ),
                                },
                                "organization_id": {
                                    "type": "string",
                                    "description": "UUID of the linked organization.",
                                },
                                "owner_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": (
                                        "Replaces the whole owner list. Each entry is "
                                        "a teammate's user UUID or exact email. [] "
                                        "removes all owners."
                                    ),
                                },
                                "source": {
                                    "type": "string",
                                    "enum": [m.value for m in CrmContactSource],
                                },
                                "status": {
                                    "type": "string",
                                    "enum": self._stage_options,
                                    "description": "Contact stage.",
                                },
                                "category": category_schema,
                                "party_affiliation": {"type": "string"},
                                "us_state": {
                                    "type": "string",
                                    "description": "2-letter US state code.",
                                },
                                "principal": {
                                    "type": "string",
                                    "description": (
                                        "For staffers, the official they work for."
                                    ),
                                },
                                "notes": {"type": "string"},
                                "linkedin_url": {"type": "string"},
                                "location": {"type": "string"},
                                "profile_picture_url": {
                                    "type": "string",
                                    "description": "Image URL to download; null clears.",
                                },
                                "add_tag_ids": {
                                    **tag_ids_schema,
                                    "description": (
                                        "Contact/organization: existing tag UUIDs to "
                                        "add. Other tags stay."
                                    ),
                                },
                                "remove_tag_ids": {
                                    **tag_ids_schema,
                                    "description": (
                                        "Contact/organization: tag UUIDs to remove."
                                    ),
                                },
                                "name": {"type": "string"},
                                "website": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "description": (
                                        "Organization: "
                                        f"{'|'.join(m.value for m in CrmOrganizationType)}. "
                                        "Interaction: "
                                        f"{'|'.join(m.value for m in CrmInteractionType)}."
                                    ),
                                },
                                "sector": {"type": "string"},
                                "size": {"type": "string"},
                                "summary": {"type": "string"},
                                "occurred_at": {
                                    "type": "string",
                                    "description": "ISO datetime.",
                                },
                                "contact_id": {
                                    "type": "string",
                                    "description": (
                                        "Interaction: UUID of the primary contact."
                                    ),
                                },
                                "attendees": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                    "description": (
                                        "Interaction: replaces all attendees. Items "
                                        "are {email|name|contact_id|user_id, role}. "
                                        "Omit to keep attendees; [] removes all."
                                    ),
                                },
                            },
                        },
                    },
                    "required": ["entity_type", "entity_id", "updates"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmUpdateToolStart()))

    def _download_profile_picture(self, url: str) -> str:
        try:
            return save_file_from_url(
                url,
                display_name="crm_profile_picture",
                file_origin=FileOrigin.CRM_UPLOAD,
                require_image=True,
            )
        except Exception as e:
            logger.warning(
                "Failed to download CRM contact profile picture during update: %s", e
            )
            raise ToolCallException(
                message=f"Failed to download CRM contact profile picture from {url}: {e}",
                llm_facing_message=(
                    f"I could not download the image from {url!r}, so the contact "
                    "was not updated. Use a reachable image URL."
                ),
            ) from e

    def _normalize_contact_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Column patches for update_contact. Owners and tags are handled by the
        caller. A profile picture is downloaded last, after all other checks."""
        normalized_updates = {
            key: value
            for key, value in updates.items()
            if key not in ("owner_ids", *TAG_CHANGE_FIELDS)
        }
        picture_url: str | None = None
        if "profile_picture_url" in normalized_updates:
            profile_picture_url = normalized_updates.pop("profile_picture_url")
            if profile_picture_url is not None and not isinstance(
                profile_picture_url, str
            ):
                raise ToolCallException(
                    message=f"Invalid profile_picture_url payload type: {type(profile_picture_url)}",
                    llm_facing_message="'updates.profile_picture_url' must be a string URL or null.",
                )
            picture_url = (profile_picture_url or "").strip() or None
            if picture_url is None:
                normalized_updates["profile_picture_file_id"] = None

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

        if picture_url is not None:
            normalized_updates["profile_picture_file_id"] = (
                self._download_profile_picture(picture_url)
            )
        return normalized_updates

    def _normalize_organization_updates(
        self, updates: dict[str, Any]
    ) -> dict[str, Any]:
        normalized_updates = {
            key: value for key, value in updates.items() if key not in TAG_CHANGE_FIELDS
        }
        if "type" in normalized_updates:
            normalized_updates["type"] = parse_enum_maybe(
                CrmOrganizationType,
                normalized_updates.get("type"),
                "updates.type",
            )
        return normalized_updates

    def _normalize_interaction_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Column patches for update_interaction ('attendees' excluded)."""
        normalized_updates = {
            key: value for key, value in updates.items() if key != "attendees"
        }

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

    def _validate_updates(self, entity_type: str, updates: dict[str, Any]) -> None:
        if not updates:
            raise ToolCallException(
                message=f"Empty updates in {self.name}",
                llm_facing_message=(
                    "'updates' is empty. Send at least one field to change."
                ),
            )
        if "tag_ids" in updates and entity_type != "interaction":
            raise ToolCallException(
                message=f"tag_ids sent to {self.name}",
                llm_facing_message=(
                    "'updates.tag_ids' is not supported. Use 'add_tag_ids' and/or "
                    "'remove_tag_ids' to change tags; other tags stay as they are. "
                    "Nothing was saved."
                ),
            )
        reject_unknown_keys(
            updates, UPDATE_FIELDS_BY_ENTITY_TYPE[entity_type], "updates"
        )

    def _parse_tag_changes(
        self, db_session: Session, updates: dict[str, Any]
    ) -> tuple[list[CrmTag], list[CrmTag]]:
        add_ids = (
            parse_uuid_list(updates["add_tag_ids"], "updates.add_tag_ids")
            if "add_tag_ids" in updates
            else []
        )
        remove_ids = (
            parse_uuid_list(updates["remove_tag_ids"], "updates.remove_tag_ids")
            if "remove_tag_ids" in updates
            else []
        )
        overlap = [str(tag_id) for tag_id in add_ids if tag_id in remove_ids]
        if overlap:
            raise ToolCallException(
                message=f"Tag IDs in both add and remove: {overlap}",
                llm_facing_message=(
                    "These tag IDs are in both 'add_tag_ids' and 'remove_tag_ids': "
                    f"{', '.join(overlap)}."
                ),
            )
        return (
            require_tags(db_session, add_ids, "updates.add_tag_ids"),
            require_tags(db_session, remove_ids, "updates.remove_tag_ids"),
        )

    def _require_organization(
        self, db_session: Session, organization_id: UUID | None
    ) -> None:
        if organization_id is not None and (
            get_organization_by_id(organization_id, db_session) is None
        ):
            raise ToolCallException(
                message=f"Organization not found: {organization_id}",
                llm_facing_message="Could not find the provided organization_id.",
            )

    def _update_contact(
        self, db_session: Session, contact: CrmContact, updates: dict[str, Any]
    ) -> dict[str, Any]:
        with crm_write_errors("update") as write:
            tags_to_add, tags_to_remove = self._parse_tag_changes(db_session, updates)
            owner_ids = (
                resolve_owner_ids(db_session, updates["owner_ids"], "updates.owner_ids")
                if "owner_ids" in updates
                else None
            )
            self._require_organization(
                db_session,
                parse_uuid_maybe(
                    updates.get("organization_id"), "updates.organization_id"
                ),
            )
            if updates.get("profile_picture_url"):
                # End the read transaction: no connection is held during the
                # download.
                db_session.commit()
            patches = self._normalize_contact_updates(updates)
            if patches.get("profile_picture_file_id"):
                write.stored_file_ids.append(patches["profile_picture_file_id"])
            if owner_ids is not None:
                patches["owner_ids"] = owner_ids

            _, changed = update_contact(
                db_session=db_session, contact=contact, patches=patches, commit=False
            )
            tags_added = [
                tag
                for tag in tags_to_add
                if add_tag_to_contact(
                    db_session, contact_id=contact.id, tag_id=tag.id, commit=False
                )
            ]
            tags_removed = [
                tag
                for tag in tags_to_remove
                if remove_tag_from_contact(
                    db_session, contact_id=contact.id, tag_id=tag.id, commit=False
                )
            ]
            # Commit expires loaded rows, so the serializers re-read updated_at
            # as the triggers left it.
            db_session.commit()
        return {
            "status": "updated"
            if changed or tags_added or tags_removed
            else "no_changes",
            "entity_type": "contact",
            "tags_added": _tag_refs(tags_added),
            "tags_removed": _tag_refs(tags_removed),
            "contact": serialize_contacts(db_session, [contact])[0],
        }

    def _update_organization(
        self,
        db_session: Session,
        organization: CrmOrganization,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        with crm_write_errors("update"):
            tags_to_add, tags_to_remove = self._parse_tag_changes(db_session, updates)
            patches = self._normalize_organization_updates(updates)

            _, changed = update_organization(
                db_session=db_session,
                organization=organization,
                patches=patches,
                commit=False,
            )
            tags_added = [
                tag
                for tag in tags_to_add
                if add_tag_to_organization(
                    db_session,
                    organization_id=organization.id,
                    tag_id=tag.id,
                    commit=False,
                )
            ]
            tags_removed = [
                tag
                for tag in tags_to_remove
                if remove_tag_from_organization(
                    db_session,
                    organization_id=organization.id,
                    tag_id=tag.id,
                    commit=False,
                )
            ]
            db_session.commit()
        return {
            "status": "updated"
            if changed or tags_added or tags_removed
            else "no_changes",
            "entity_type": "organization",
            "tags_added": _tag_refs(tags_added),
            "tags_removed": _tag_refs(tags_removed),
            "organization": serialize_organization(
                organization,
                tags=get_organization_tags(organization.id, db_session),
            ),
        }

    def _update_interaction(
        self, db_session: Session, entity_id: UUID, updates: dict[str, Any]
    ) -> dict[str, Any]:
        interaction = get_interaction_by_id(entity_id, db_session)
        if interaction is None:
            raise ToolCallException(
                message=f"Interaction not found: {entity_id}",
                llm_facing_message="Could not find the specified interaction.",
            )

        patches = self._normalize_interaction_updates(updates)
        if patches.get("contact_id") is not None:
            if get_contact_by_id(patches["contact_id"], db_session) is None:
                raise ToolCallException(
                    message=f"Contact not found: {patches['contact_id']}",
                    llm_facing_message="Could not find the provided contact_id.",
                )
        self._require_organization(db_session, patches.get("organization_id"))

        # Resolve attendees before any write so a failure leaves the
        # interaction untouched.
        attendees_present = "attendees" in updates
        attendee_resolution_details: list[dict[str, Any]] = []
        attendee_tuples: list[tuple[UUID | None, UUID | None, CrmAttendeeRole]] = []
        if attendees_present:
            attendees_raw = updates["attendees"]
            if attendees_raw is not None and not isinstance(attendees_raw, list):
                raise ToolCallException(
                    message=f"Invalid attendees payload in crm_update: {type(attendees_raw)}",
                    llm_facing_message="'updates.attendees' must be an array.",
                )
            (
                resolved_attendees,
                unresolved_attendees,
                attendee_resolution_details,
            ) = resolve_attendees(
                db_session=db_session,
                attendees_to_resolve=attendees_raw or [],
            )

            if unresolved_attendees:
                # 'attendees' replaces the full list, so applying only the
                # resolved subset would silently drop people.
                unresolved_summary = json.dumps(unresolved_attendees, default=str)
                raise ToolCallException(
                    message=f"Unresolved attendees in crm_update: {unresolved_summary}",
                    llm_facing_message=(
                        "The interaction was NOT updated because some attendees "
                        "could not be resolved and 'updates.attendees' replaces the "
                        "full attendee list. Unresolved attendees (with candidate "
                        f"matches): {unresolved_summary}. Retry with exact "
                        "contact_id/user_id values or corrected emails/names, or "
                        "omit 'attendees' to leave the attendee list unchanged."
                    ),
                )

            attendee_tuples = [
                (attendee["user_id"], attendee["contact_id"], attendee["role"])
                for attendee in resolved_attendees
            ]

        with crm_write_errors("update"):
            _, changed = update_interaction(
                db_session=db_session,
                interaction=interaction,
                patches=patches,
                commit=False,
            )
            if attendees_present:
                attendees_changed = replace_interaction_attendees(
                    db_session=db_session,
                    interaction_id=interaction.id,
                    attendees=attendee_tuples,
                    commit=False,
                )
                changed = changed or attendees_changed
            db_session.commit()

        payload: dict[str, Any] = {
            "status": "updated" if changed else "no_changes",
            "entity_type": "interaction",
            "interaction": serialize_interactions(db_session, [interaction])[0],
        }
        if attendee_resolution_details:
            payload["attendee_resolution"] = attendee_resolution_details
        return payload

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        reject_unknown_keys(llm_kwargs, TOP_LEVEL_FIELDS, "crm_update arguments")

        entity_type = parse_entity_type(
            llm_kwargs.get("entity_type"), CRM_UPDATE_ENTITY_TYPES, self.name
        )

        entity_id = parse_uuid_maybe(llm_kwargs.get("entity_id"), "entity_id")
        if not entity_id:
            raise ToolCallException(
                message=f"Missing/invalid entity_id in {self.name}",
                llm_facing_message="'entity_id' must be a valid UUID.",
            )

        updates = llm_kwargs.get("updates")
        if not isinstance(updates, dict):
            raise ToolCallException(
                message=f"Missing updates object in {self.name}",
                llm_facing_message="'updates' must be an object with fields to update.",
            )
        self._validate_updates(entity_type, updates)

        with self._session_factory() as db_session:
            if entity_type == "contact":
                contact = get_contact_by_id(entity_id, db_session)
                if contact is None:
                    raise ToolCallException(
                        message=f"Contact not found: {entity_id}",
                        llm_facing_message="Could not find the specified contact.",
                    )
                payload = self._update_contact(db_session, contact, updates)
            elif entity_type == "organization":
                organization = get_organization_by_id(entity_id, db_session)
                if organization is None:
                    raise ToolCallException(
                        message=f"Organization not found: {entity_id}",
                        llm_facing_message="Could not find the specified organization.",
                    )
                payload = self._update_organization(db_session, organization, updates)
            else:
                payload = self._update_interaction(db_session, entity_id, updates)

        return crm_tool_response(self.emitter, placement, payload, CrmUpdateToolDelta)
