from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.configs.constants import FileOrigin
from onyx.db.crm import (
    add_tag_to_contact,
    add_tag_to_organization,
    create_contact,
    create_organization,
    create_tag,
    get_allowed_contact_stages,
    get_contact_by_email,
    get_contact_category_options,
    get_organization_by_id,
    get_organization_tags,
)
from onyx.db.enums import CrmContactSource, CrmOrganizationType
from onyx.db.models import CrmTag
from onyx.file_store.utils import save_file_from_url
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CrmCreateToolDelta,
    CrmCreateToolStart,
    Packet,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolResponse
from onyx.tools.tool_implementations.crm.models import (
    add_similar_principals,
    crm_tool_response,
    is_crm_schema_available,
    parse_enum_maybe,
    parse_stage_maybe,
    parse_uuid_maybe,
    serialize_contacts,
    serialize_organization,
    serialize_tag,
)
from onyx.tools.tool_implementations.crm.validation import (
    crm_write_errors,
    delete_file_best_effort,
    parse_entity_type,
    parse_uuid_list,
    reject_unknown_keys,
    require_tags,
    resolve_owner_ids,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

CONTACT_CREATE_FIELDS = (
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
    "tag_ids",
)
ORGANIZATION_CREATE_FIELDS = (
    "name",
    "website",
    "type",
    "sector",
    "location",
    "size",
    "notes",
    "tag_ids",
)
TAG_CREATE_FIELDS = ("name", "color")
CREATE_FIELDS_BY_ENTITY_TYPE = {
    "contact": CONTACT_CREATE_FIELDS,
    "organization": ORGANIZATION_CREATE_FIELDS,
    "tag": TAG_CREATE_FIELDS,
}
CRM_CREATE_ENTITY_TYPES = set(CREATE_FIELDS_BY_ENTITY_TYPE)


def _tag_refs(tags: list[CrmTag]) -> list[dict[str, str]]:
    return [{"id": str(tag.id), "name": tag.name} for tag in tags]


def _not_applied_fields(data: dict[str, Any], applied: tuple[str, ...]) -> list[str]:
    return sorted(key for key in data if key not in applied)


class CrmCreateTool(Tool[None]):
    NAME = "crm_create"
    DISPLAY_NAME = "CRM Create"
    DESCRIPTION = (
        "Create a contact, organization, or tag. An existing email (contact) or name "
        "(org, tag; ignoring case) returns 'already_exists': contact/org tags are "
        "still added, other supplied fields are not (listed in not_applied_fields). "
        "Use crm_update to change existing contacts/orgs."
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
        category_schema: dict[str, Any] = (
            {
                "type": "string",
                "enum": self._category_options,
                "description": (
                    "Contact category. Choose the most specific applicable option."
                ),
            }
            if self._category_options
            else {
                "type": "string",
                "description": "Optional contact category label.",
            }
        )
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
                            "description": "Contact payload when entity_type is 'contact'. Provide at least one of first_name or last_name.",
                            "properties": {
                                "first_name": {
                                    "type": "string",
                                    "description": "First name. Optional, but provide at least one of first_name or last_name.",
                                },
                                "last_name": {
                                    "type": "string",
                                    "description": "Last name. Optional, but provide at least one of first_name or last_name.",
                                },
                                "email": {
                                    "type": "string",
                                    "description": "Email address. If a contact with this email exists, it is returned instead.",
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
                                        "Owners: each entry is a teammate's user UUID "
                                        "or exact email. Omit to make the current user "
                                        "the owner; [] sets no owners."
                                    ),
                                },
                                "source": {
                                    "type": "string",
                                    "enum": [
                                        "manual",
                                        "import",
                                        "referral",
                                        "inbound",
                                        "other",
                                    ],
                                    "description": "How this contact entered the system.",
                                },
                                "status": {
                                    "type": "string",
                                    "enum": self._stage_options,
                                    "description": "Contact lifecycle stage.",
                                },
                                "category": category_schema,
                                "party_affiliation": {
                                    "type": "string",
                                    "description": (
                                        "Political party affiliation, e.g. 'Democrat', "
                                        "'Republican', 'Social Democrat'."
                                    ),
                                },
                                "us_state": {
                                    "type": "string",
                                    "description": (
                                        "2-letter US state abbreviation (e.g. 'CA'). "
                                        "Use for members of the US House/Senate and "
                                        "state-level policy makers."
                                    ),
                                },
                                "principal": {
                                    "type": "string",
                                    "description": (
                                        "For staffers: the name of the principal they "
                                        "work for, e.g. the Senator or Representative. "
                                        "Reuse the exact spelling other contacts "
                                        "already use for the same official."
                                    ),
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
                                "profile_picture_url": {
                                    "type": "string",
                                    "description": "Remote image URL to download and attach as the contact's profile picture.",
                                },
                                "tag_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "UUIDs of existing tags to apply.",
                                },
                            },
                        },
                        "organization": {
                            "type": "object",
                            "description": "Organization payload when entity_type is 'organization'. Required field: name.",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Organization name (required).",
                                },
                                "website": {
                                    "type": "string",
                                    "description": "Website URL.",
                                },
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "customer",
                                        "prospect",
                                        "partner",
                                        "vendor",
                                        "other",
                                    ],
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
                                    "description": "UUIDs of existing tags to apply.",
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

    def _parse_tag_ids(
        self, db_session: Session, data: dict[str, Any], field_name: str
    ) -> list[CrmTag]:
        if data.get("tag_ids") is None:
            return []
        return require_tags(
            db_session, parse_uuid_list(data["tag_ids"], field_name), field_name
        )

    def _download_profile_picture(self, url: str) -> tuple[str | None, str | None]:
        """Returns (file_id, warning). A failed download does not block creation."""
        try:
            file_id = save_file_from_url(
                url,
                display_name="crm_profile_picture",
                file_origin=FileOrigin.CRM_UPLOAD,
                require_image=True,
            )
        except Exception as e:
            logger.warning(
                "Failed to download CRM contact profile picture during create: %s", e
            )
            return None, (
                f"Could not download the profile picture from {url!r} ({e}). The "
                "contact was saved without it; retry with crm_update "
                "profile_picture_url and a reachable image URL."
            )
        return file_id, None

    def _create_contact(
        self, db_session: Session, contact_data: dict[str, Any]
    ) -> dict[str, Any]:
        reject_unknown_keys(contact_data, CONTACT_CREATE_FIELDS, "contact")
        first_name = contact_data.get("first_name")
        last_name = contact_data.get("last_name")
        has_first = isinstance(first_name, str) and bool(first_name.strip())
        has_last = isinstance(last_name, str) and bool(last_name.strip())
        if not has_first and not has_last:
            raise ToolCallException(
                message="Missing name for CRM contact creation",
                llm_facing_message=(
                    "Provide at least one of 'contact.first_name' or "
                    "'contact.last_name' to create a contact."
                ),
            )

        organization_id = parse_uuid_maybe(
            contact_data.get("organization_id"), "contact.organization_id"
        )
        if organization_id:
            organization = get_organization_by_id(organization_id, db_session)
            if organization is None:
                raise ToolCallException(
                    message=f"Organization not found: {organization_id}",
                    llm_facing_message="Could not find the provided organization_id.",
                )

        if "owner_ids" in contact_data:
            owner_ids = resolve_owner_ids(
                db_session, contact_data["owner_ids"], "contact.owner_ids"
            )
        else:
            creator_id = parse_uuid_maybe(self._user_id, "user_id")
            owner_ids = (
                resolve_owner_ids(db_session, [str(creator_id)], "owner_ids")
                if creator_id is not None
                else []
            )

        source = parse_enum_maybe(
            CrmContactSource, contact_data.get("source"), "contact.source"
        )
        status = parse_stage_maybe(
            contact_data.get("status"),
            allowed_stages=self._stage_options,
            field_name="contact.status",
        )
        if status is None:
            status = self._stage_options[0]
        tags = self._parse_tag_ids(db_session, contact_data, "contact.tag_ids")

        profile_picture_url = contact_data.get("profile_picture_url")
        if profile_picture_url is not None and not isinstance(profile_picture_url, str):
            raise ToolCallException(
                message=f"Invalid profile_picture_url payload type: {type(profile_picture_url)}",
                llm_facing_message="'contact.profile_picture_url' must be a string URL.",
            )
        picture_url = (profile_picture_url or "").strip()
        email = contact_data.get("email")

        warnings: list[str] = []
        with crm_write_errors("create") as write:
            profile_picture_file_id: str | None = None
            if picture_url and not (
                isinstance(email, str) and get_contact_by_email(email, db_session)
            ):
                # End the read transaction: no connection is held during the
                # download.
                db_session.commit()
                profile_picture_file_id, warning = self._download_profile_picture(
                    picture_url
                )
                if warning:
                    warnings.append(warning)
                if profile_picture_file_id:
                    write.stored_file_ids.append(profile_picture_file_id)

            contact, created = create_contact(
                db_session=db_session,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=contact_data.get("phone"),
                title=contact_data.get("title"),
                organization_id=organization_id,
                owner_ids=owner_ids,
                source=source,
                status=status,
                category=contact_data.get("category"),
                party_affiliation=contact_data.get("party_affiliation"),
                us_state=contact_data.get("us_state"),
                principal=contact_data.get("principal"),
                notes=contact_data.get("notes"),
                linkedin_url=contact_data.get("linkedin_url"),
                location=contact_data.get("location"),
                profile_picture_file_id=profile_picture_file_id,
                created_by=parse_uuid_maybe(self._user_id, "user_id"),
                commit=False,
            )
            tags_added = [
                tag
                for tag in tags
                if add_tag_to_contact(
                    db_session, contact_id=contact.id, tag_id=tag.id, commit=False
                )
            ]
            # Commit expires loaded rows, so the serializer re-reads updated_at as
            # the triggers left it.
            db_session.commit()
            if not created and profile_picture_file_id:
                # Another call created the contact first; the picture is unused.
                delete_file_best_effort(profile_picture_file_id)

        payload: dict[str, Any] = {
            "status": "created" if created else "already_exists",
            "entity_type": "contact",
            "tags_added": _tag_refs(tags_added),
            "contact": serialize_contacts(db_session, [contact])[0],
        }
        if not created:
            payload["not_applied_fields"] = _not_applied_fields(
                contact_data, ("email", "tag_ids")
            )
            payload["note"] = (
                "A contact with this email already exists. Use crm_update to change it."
            )
        else:
            add_similar_principals(db_session, payload, contact_data.get("principal"))
        if warnings:
            payload["warnings"] = warnings
        return payload

    def _create_organization(
        self, db_session: Session, organization_data: dict[str, Any]
    ) -> dict[str, Any]:
        reject_unknown_keys(
            organization_data, ORGANIZATION_CREATE_FIELDS, "organization"
        )
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
        tags = self._parse_tag_ids(
            db_session, organization_data, "organization.tag_ids"
        )

        with crm_write_errors("create"):
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
                commit=False,
            )
            tags_added = [
                tag
                for tag in tags
                if add_tag_to_organization(
                    db_session,
                    organization_id=organization.id,
                    tag_id=tag.id,
                    commit=False,
                )
            ]
            db_session.commit()

        payload: dict[str, Any] = {
            "status": "created" if created else "already_exists",
            "entity_type": "organization",
            "tags_added": _tag_refs(tags_added),
            "organization": serialize_organization(
                organization, tags=get_organization_tags(organization.id, db_session)
            ),
        }
        if not created:
            payload["not_applied_fields"] = _not_applied_fields(
                organization_data, ("name", "tag_ids")
            )
            payload["note"] = (
                "An organization with this name already exists. Use crm_update to "
                "change it."
            )
        return payload

    def _create_tag(
        self, db_session: Session, tag_data: dict[str, Any]
    ) -> dict[str, Any]:
        reject_unknown_keys(tag_data, TAG_CREATE_FIELDS, "tag")
        name = tag_data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ToolCallException(
                message="Missing name for CRM tag creation",
                llm_facing_message="'tag.name' is required to create a tag.",
            )

        with crm_write_errors("create"):
            tag, created = create_tag(
                db_session=db_session,
                name=name,
                color=tag_data.get("color"),
                commit=False,
            )
            db_session.commit()

        payload: dict[str, Any] = {
            "status": "created" if created else "already_exists",
            "entity_type": "tag",
            "tag": serialize_tag(tag),
        }
        if not created:
            payload["not_applied_fields"] = _not_applied_fields(tag_data, ("name",))
            payload["note"] = "A tag with this name already exists; use its id."
        return payload

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        reject_unknown_keys(
            llm_kwargs,
            ("entity_type", *CREATE_FIELDS_BY_ENTITY_TYPE),
            "crm_create arguments",
        )
        entity_type = parse_entity_type(
            llm_kwargs.get("entity_type"), CRM_CREATE_ENTITY_TYPES, self.name
        )

        misplaced = sorted(
            key
            for key in CREATE_FIELDS_BY_ENTITY_TYPE
            if key != entity_type and llm_kwargs.get(key)
        )
        if misplaced:
            raise ToolCallException(
                message=f"Payloads for other entity types in {self.name}: {misplaced}",
                llm_facing_message=(
                    f"{', '.join(repr(key) for key in misplaced)} does not apply when "
                    f"entity_type is '{entity_type}'. Put the fields in "
                    f"'{entity_type}', or make a separate call. Nothing was saved."
                ),
            )

        data = llm_kwargs.get(entity_type)
        if not isinstance(data, dict):
            raise ToolCallException(
                message=f"Missing {entity_type} payload for {self.name}",
                llm_facing_message=(
                    f"'{entity_type}' must be provided as an object when "
                    f"entity_type is '{entity_type}'."
                ),
            )

        with self._session_factory() as db_session:
            if entity_type == "contact":
                payload = self._create_contact(db_session, data)
            elif entity_type == "organization":
                payload = self._create_organization(db_session, data)
            else:
                payload = self._create_tag(db_session, data)

        return crm_tool_response(self.emitter, placement, payload, CrmCreateToolDelta)
