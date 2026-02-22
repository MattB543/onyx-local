from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import get_allowed_contact_stages
from onyx.db.crm import get_contact_by_id
from onyx.db.crm import get_contact_owner_ids
from onyx.db.crm import get_contact_tags
from onyx.db.crm import get_organization_by_id
from onyx.db.crm import get_organization_tags
from onyx.db.crm import update_contact
from onyx.db.crm import update_organization
from onyx.db.enums import CrmContactSource
from onyx.db.enums import CrmOrganizationType
from onyx.db.models import User
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CrmUpdateToolDelta
from onyx.server.query_and_chat.streaming_models import CrmUpdateToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.crm.models import as_llm_json
from onyx.tools.tool_implementations.crm.models import compact_tool_payload_for_model
from onyx.tools.tool_implementations.crm.models import is_crm_schema_available
from onyx.tools.tool_implementations.crm.models import parse_enum_maybe
from onyx.tools.tool_implementations.crm.models import parse_stage_maybe
from onyx.tools.tool_implementations.crm.models import parse_uuid_maybe
from onyx.tools.tool_implementations.crm.models import serialize_contact
from onyx.tools.tool_implementations.crm.models import serialize_organization


CRM_UPDATE_ENTITY_TYPES = {"contact", "organization"}


class CrmUpdateTool(Tool[None]):
    NAME = "crm_update"
    DISPLAY_NAME = "CRM Update"
    DESCRIPTION = (
        "Update fields on an existing CRM contact or organization. Requires the entity's UUID "
        "(from a prior search, list, or create). Only include fields you want to change in the "
        "updates object — omitted fields are left unchanged. Use this to fix info, change status, "
        "reassign ownership, or link a contact to an organization."
    )

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._session_factory = sessionmaker(bind=db_session.get_bind())
        self._stage_options = get_allowed_contact_stages(db_session)

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
                            "description": "Whether to update a 'contact' or 'organization'.",
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
                                "status (workspace-defined contact stages), category, notes, linkedin_url, location. "
                                "For organizations: name, website, type (customer|prospect|partner|vendor|other), "
                                "sector, location, size, notes."
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
                    parsed_owner_id = parse_uuid_maybe(owner_id_raw, "updates.owner_ids[]")
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

    def _normalize_organization_updates(self, updates: dict[str, Any]) -> dict[str, Any]:
        normalized_updates = dict(updates)
        if "type" in normalized_updates:
            normalized_updates["type"] = parse_enum_maybe(
                CrmOrganizationType,
                normalized_updates.get("type"),
                "updates.type",
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
                llm_facing_message="'entity_type' must be one of: contact, organization.",
            )

        entity_type = entity_type_raw.strip().lower()
        if entity_type not in CRM_UPDATE_ENTITY_TYPES:
            raise ToolCallException(
                message=f"Unsupported entity_type in {self.name}: {entity_type}",
                llm_facing_message="'entity_type' must be one of: contact, organization.",
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
                        organization = get_organization_by_id(updates["organization_id"], db_session)
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

                    updated_contact = update_contact(
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
                else:
                    organization = get_organization_by_id(entity_id, db_session)
                    if organization is None:
                        raise ToolCallException(
                            message=f"Organization not found: {entity_id}",
                            llm_facing_message="Could not find the specified organization.",
                        )

                    updates = self._normalize_organization_updates(updates_raw)
                    updated_organization = update_organization(
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
