from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import add_tag_to_contact
from onyx.db.crm import add_tag_to_organization
from onyx.db.crm import create_contact
from onyx.db.crm import create_organization
from onyx.db.crm import create_tag
from onyx.db.crm import get_allowed_contact_stages
from onyx.db.crm import get_contact_owner_ids
from onyx.db.crm import get_contact_tags
from onyx.db.crm import get_organization_by_id
from onyx.db.crm import get_organization_tags
from onyx.db.crm import get_tag_by_id
from onyx.db.enums import CrmContactSource
from onyx.db.enums import CrmOrganizationType
from onyx.db.models import User
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CrmCreateToolDelta
from onyx.server.query_and_chat.streaming_models import CrmCreateToolStart
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
from onyx.tools.tool_implementations.crm.models import serialize_tag


CRM_CREATE_ENTITY_TYPES = {"contact", "organization", "tag"}


class CrmCreateTool(Tool[None]):
    NAME = "crm_create"
    DISPLAY_NAME = "CRM Create"
    DESCRIPTION = (
        "Create a new CRM contact, organization, or tag. Always search first to avoid duplicates. "
        "When creating a contact, set organization_id to link them to an existing org, and include "
        "tag_ids to apply tags. New contacts default to the workspace's default stage. "
        "Confirm what you created back to the user with key details."
    )

    def __init__(
        self,
        tool_id: int,
        db_session: Session,
        emitter: Emitter,
        user_id: str | None,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._user_id = user_id
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
                            "enum": sorted(list(CRM_CREATE_ENTITY_TYPES)),
                            "description": "Which CRM entity to create.",
                        },
                        "contact": {
                            "type": "object",
                            "description": "Contact payload when entity_type is 'contact'. Required field: first_name.",
                            "properties": {
                                "first_name": {
                                    "type": "string",
                                    "description": "First name (required).",
                                },
                                "last_name": {
                                    "type": "string",
                                    "description": "Last name.",
                                },
                                "email": {
                                    "type": "string",
                                    "description": "Email address. Used for deduplication — if a contact with this email exists, returns the existing one.",
                                },
                                "phone": {
                                    "type": "string",
                                    "description": "Phone number.",
                                },
                                "title": {
                                    "type": "string",
                                    "description": "Job title (e.g. 'Lead Dev', 'CEO', 'Account Manager').",
                                },
                                "organization_id": {
                                    "type": "string",
                                    "description": "UUID of an existing organization to link this contact to.",
                                },
                                "owner_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": (
                                        "UUIDs of team members who own this contact. "
                                        "If omitted, defaults to the user invoking this tool. "
                                        "Use [] to intentionally set no owners."
                                    ),
                                },
                                "source": {
                                    "type": "string",
                                    "enum": ["manual", "import", "referral", "inbound", "other"],
                                    "description": "How this contact entered the system.",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": self._stage_options,
                                    "description": "Contact lifecycle stage.",
                                },
                                "category": {
                                    "type": "string",
                                    "description": "Optional contact category label.",
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "Free-text notes about this contact.",
                                },
                                "linkedin_url": {
                                    "type": "string",
                                    "description": "LinkedIn profile URL.",
                                },
                                "location": {
                                    "type": "string",
                                    "description": "Location (e.g. 'San Francisco, CA').",
                                },
                                "tag_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "UUIDs of existing tags to apply to this contact.",
                                },
                            },
                            "required": ["first_name"],
                        },
                        "organization": {
                            "type": "object",
                            "description": "Organization payload when entity_type is 'organization'. Required field: name.",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Organization name (required). Used for deduplication.",
                                },
                                "website": {
                                    "type": "string",
                                    "description": "Website URL.",
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["customer", "prospect", "partner", "vendor", "other"],
                                    "description": "Relationship type.",
                                },
                                "sector": {
                                    "type": "string",
                                    "description": "Industry sector (e.g. 'Technology', 'Healthcare').",
                                },
                                "location": {
                                    "type": "string",
                                    "description": "Location (e.g. 'New York, NY').",
                                },
                                "size": {
                                    "type": "string",
                                    "description": "Company size (e.g. '50-100', '1000+').",
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "Free-text notes about this organization.",
                                },
                                "tag_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "UUIDs of existing tags to apply to this organization.",
                                },
                            },
                            "required": ["name"],
                        },
                        "tag": {
                            "type": "object",
                            "description": "Tag payload when entity_type is 'tag'. Required field: name.",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Tag name (required).",
                                },
                                "color": {
                                    "type": "string",
                                    "description": "Tag color (e.g. 'blue', '#FF5733').",
                                },
                            },
                            "required": ["name"],
                        },
                    },
                    "required": ["entity_type"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmCreateToolStart()))

    def _create_contact(self, db_session: Session, contact_data: dict[str, Any]) -> dict[str, Any]:
        first_name = contact_data.get("first_name")
        if not isinstance(first_name, str) or not first_name.strip():
            raise ToolCallException(
                message="Missing first_name for CRM contact creation",
                llm_facing_message="'contact.first_name' is required to create a contact.",
            )

        organization_id = parse_uuid_maybe(contact_data.get("organization_id"), "contact.organization_id")
        if organization_id:
            organization = get_organization_by_id(organization_id, db_session)
            if organization is None:
                raise ToolCallException(
                    message=f"Organization not found: {organization_id}",
                    llm_facing_message="Could not find the provided organization_id.",
                )

        owner_ids: list[UUID] = []
        if "owner_ids" in contact_data:
            owner_ids_raw = contact_data.get("owner_ids")
            if owner_ids_raw is None:
                owner_ids = []
            elif isinstance(owner_ids_raw, list):
                owner_ids = [
                    parsed_owner_id
                    for owner_id_raw in owner_ids_raw
                    if (parsed_owner_id := parse_uuid_maybe(owner_id_raw, "contact.owner_ids[]"))
                    is not None
                ]
            else:
                raise ToolCallException(
                    message=f"Invalid owner_ids payload type: {type(owner_ids_raw)}",
                    llm_facing_message="'contact.owner_ids' must be an array of UUID strings.",
                )
        else:
            creator_id = parse_uuid_maybe(self._user_id, "user_id")
            owner_ids = [creator_id] if creator_id is not None else []

        for owner_id in owner_ids:
            if db_session.get(User, owner_id) is not None:
                continue
            raise ToolCallException(
                message=f"Owner user not found: {owner_id}",
                llm_facing_message="Could not find one of the provided contact owner user IDs.",
            )

        source = parse_enum_maybe(CrmContactSource, contact_data.get("source"), "contact.source")
        status = parse_stage_maybe(
            contact_data.get("status"),
            allowed_stages=self._stage_options,
            field_name="contact.status",
        )
        if status is None:
            status = self._stage_options[0]

        contact, created = create_contact(
            db_session=db_session,
            first_name=first_name,
            last_name=contact_data.get("last_name"),
            email=contact_data.get("email"),
            phone=contact_data.get("phone"),
            title=contact_data.get("title"),
            organization_id=organization_id,
            owner_ids=owner_ids,
            source=source,
            status=status,
            category=contact_data.get("category"),
            notes=contact_data.get("notes"),
            linkedin_url=contact_data.get("linkedin_url"),
            location=contact_data.get("location"),
            created_by=parse_uuid_maybe(self._user_id, "user_id"),
        )

        for tag_id_raw in contact_data.get("tag_ids", []) or []:
            tag_id = parse_uuid_maybe(tag_id_raw, "contact.tag_ids[]")
            if not tag_id:
                continue
            if get_tag_by_id(tag_id, db_session):
                add_tag_to_contact(db_session=db_session, contact_id=contact.id, tag_id=tag_id)

        tags = get_contact_tags(contact.id, db_session)
        resolved_owner_ids = get_contact_owner_ids(contact.id, db_session)
        return {
            "status": "created" if created else "already_exists",
            "entity_type": "contact",
            "contact": serialize_contact(
                contact,
                owner_ids=resolved_owner_ids,
                tags=tags,
            ),
        }

    def _create_organization(self, db_session: Session, organization_data: dict[str, Any]) -> dict[str, Any]:
        name = organization_data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolCallException(
                message="Missing name for CRM organization creation",
                llm_facing_message="'organization.name' is required to create an organization.",
            )

        organization_type = parse_enum_maybe(
            CrmOrganizationType,
            organization_data.get("type"),
            "organization.type",
        )

        organization, created = create_organization(
            db_session=db_session,
            name=name,
            website=organization_data.get("website"),
            type=organization_type,
            sector=organization_data.get("sector"),
            location=organization_data.get("location"),
            size=organization_data.get("size"),
            notes=organization_data.get("notes"),
            created_by=parse_uuid_maybe(self._user_id, "user_id"),
        )

        for tag_id_raw in organization_data.get("tag_ids", []) or []:
            tag_id = parse_uuid_maybe(tag_id_raw, "organization.tag_ids[]")
            if not tag_id:
                continue
            if get_tag_by_id(tag_id, db_session):
                add_tag_to_organization(
                    db_session=db_session,
                    organization_id=organization.id,
                    tag_id=tag_id,
                )

        tags = get_organization_tags(organization.id, db_session)
        return {
            "status": "created" if created else "already_exists",
            "entity_type": "organization",
            "organization": serialize_organization(organization, tags=tags),
        }

    def _create_tag(self, db_session: Session, tag_data: dict[str, Any]) -> dict[str, Any]:
        name = tag_data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolCallException(
                message="Missing name for CRM tag creation",
                llm_facing_message="'tag.name' is required to create a tag.",
            )

        tag, created = create_tag(
            db_session=db_session,
            name=name,
            color=tag_data.get("color"),
        )

        return {
            "status": "created" if created else "already_exists",
            "entity_type": "tag",
            "tag": serialize_tag(tag),
        }

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
                llm_facing_message="'entity_type' must be one of: contact, organization, tag.",
            )

        entity_type = entity_type_raw.strip().lower()
        if entity_type not in CRM_CREATE_ENTITY_TYPES:
            raise ToolCallException(
                message=f"Unsupported entity_type in {self.name}: {entity_type}",
                llm_facing_message="'entity_type' must be one of: contact, organization, tag.",
            )

        with self._session_factory() as db_session:
            try:
                if entity_type == "contact":
                    contact_data = llm_kwargs.get("contact")
                    if not isinstance(contact_data, dict):
                        raise ToolCallException(
                            message="Missing contact payload for crm_create contact",
                            llm_facing_message="'contact' must be provided as an object when entity_type is 'contact'.",
                        )
                    payload = self._create_contact(db_session, contact_data)
                elif entity_type == "organization":
                    organization_data = llm_kwargs.get("organization")
                    if not isinstance(organization_data, dict):
                        raise ToolCallException(
                            message="Missing organization payload for crm_create organization",
                            llm_facing_message="'organization' must be provided as an object when entity_type is 'organization'.",
                        )
                    payload = self._create_organization(db_session, organization_data)
                else:
                    tag_data = llm_kwargs.get("tag")
                    if not isinstance(tag_data, dict):
                        raise ToolCallException(
                            message="Missing tag payload for crm_create tag",
                            llm_facing_message="'tag' must be provided as an object when entity_type is 'tag'.",
                        )
                    payload = self._create_tag(db_session, tag_data)
            except ValueError as e:
                raise ToolCallException(
                    message=f"CRM create validation failed: {e}",
                    llm_facing_message=str(e),
                )
            except IntegrityError:
                raise ToolCallException(
                    message="Unique constraint violation while creating CRM entity",
                    llm_facing_message="Create failed due to duplicate unique field value.",
                )

        compact_payload = compact_tool_payload_for_model(payload)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CrmCreateToolDelta(payload=compact_payload),
            )
        )

        rich_response = json.dumps(payload, default=str)
        llm_response = as_llm_json(compact_payload, already_compacted=True)
        return ToolResponse(
            rich_response=rich_response,
            llm_facing_response=llm_response,
        )
