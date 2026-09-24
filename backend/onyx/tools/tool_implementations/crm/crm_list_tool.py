from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.crm import (
    find_similar_principals,
    get_allowed_contact_stages,
    get_contact_category_options,
    get_organization_tags,
    list_contacts,
    list_interactions,
    list_organizations,
    list_tags,
)
from onyx.db.enums import CrmInteractionType
from onyx.server.features.crm.csv_utils import is_date_only
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CrmListToolDelta,
    CrmListToolStart,
    Packet,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolResponse
from onyx.tools.tool_implementations.crm.models import (
    crm_tool_response,
    is_crm_schema_available,
    parse_datetime_maybe,
    parse_enum_maybe,
    parse_stage_maybe,
    serialize_contacts,
    serialize_interactions,
    serialize_organization,
    serialize_tag,
)
from onyx.tools.tool_implementations.crm.validation import (
    MAX_PAGE_SIZE,
    parse_entity_type,
    parse_page,
    parse_uuid,
    parse_uuid_list,
    reject_unknown_keys,
)
from onyx.tools.tool_implementations.error_delta import stream_tool_call_error

PAGING_FIELDS = ("entity_type", "page_num", "page_size")
TIMESTAMP_FILTERS = (
    "sort_by",
    "sort_dir",
    "created_after",
    "created_before",
    "updated_after",
    "updated_before",
)
FILTERS_BY_ENTITY_TYPE: dict[str, tuple[str, ...]] = {
    "contact": (
        "status",
        "category",
        "organization_id",
        "principal",
        "tag_ids",
        *TIMESTAMP_FILTERS,
    ),
    "organization": ("tag_ids", *TIMESTAMP_FILTERS),
    "interaction": ("contact_id", "organization_id", "principal", "interaction_type"),
    "tag": (),
}
CRM_LIST_ENTITY_TYPES = set(FILTERS_BY_ENTITY_TYPE)
ALL_FIELDS = {
    *PAGING_FIELDS,
    *(name for filters in FILTERS_BY_ENTITY_TYPE.values() for name in filters),
}


def _applies_to(filter_name: str) -> str:
    entity_types = [
        entity_type
        for entity_type, filters in FILTERS_BY_ENTITY_TYPE.items()
        if filter_name in filters
    ]
    return f"Only for entity_type {' or '.join(repr(t) for t in entity_types)}."


class CrmListTool(Tool[None]):
    NAME = "crm_list"
    DISPLAY_NAME = "CRM List"
    DESCRIPTION = (
        "List CRM records by structured filters instead of keywords, e.g. all leads, "
        "contacts with a tag, an org's interactions, or contacts/orgs updated this "
        "week. A contact's or org's updated_at changes when the record or its "
        "directly related data (tags, owners, interactions) changes. Filters that "
        "don't apply to the chosen entity_type are rejected."
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
        category_filter_schema: dict[str, Any] = {
            "type": "string",
            "description": f"Contact category. {_applies_to('category')}",
        }
        if self._category_options:
            category_filter_schema["enum"] = self._category_options
        timestamp_note = _applies_to("created_after")
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
                            "enum": sorted(CRM_LIST_ENTITY_TYPES),
                        },
                        "status": {
                            "type": "string",
                            "enum": self._stage_options,
                            "description": (f"Contact stage. {_applies_to('status')}"),
                        },
                        "category": category_filter_schema,
                        "organization_id": {
                            "type": "string",
                            "description": (
                                "Organization UUID. Contacts: members of the "
                                "organization. Interactions: linked directly to "
                                "it (not its contacts' interactions)."
                            ),
                        },
                        "principal": {
                            "type": "string",
                            "description": (
                                "One official's office, matched on the principal "
                                "(case-insensitive, exact spelling). Contacts: "
                                "the official's staffers. Interactions: with any "
                                "of those staffers or with the official's linked "
                                "contact. With no results, the result lists "
                                "similar existing spellings. "
                                f"{_applies_to('principal')}"
                            ),
                        },
                        "contact_id": {
                            "type": "string",
                            "description": (
                                "Contact UUID: interactions where the contact is "
                                "the primary contact or an attendee. "
                                f"{_applies_to('contact_id')}"
                            ),
                        },
                        "interaction_type": {
                            "type": "string",
                            "enum": [member.value for member in CrmInteractionType],
                            "description": _applies_to("interaction_type"),
                        },
                        "tag_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "description": (
                                "Records that have ALL of these tag UUIDs. "
                                f"{_applies_to('tag_ids')}"
                            ),
                        },
                        "sort_by": {
                            "type": "string",
                            "enum": ["created_at", "updated_at"],
                            "description": f"Default 'updated_at'. {timestamp_note}",
                        },
                        "sort_dir": {
                            "type": "string",
                            "enum": ["asc", "desc"],
                            "description": (
                                f"Default 'desc' (newest first). {timestamp_note}"
                            ),
                        },
                        "created_after": {
                            "type": "string",
                            "description": (
                                "ISO date or datetime, inclusive, e.g. "
                                f"'2026-01-01'. {timestamp_note}"
                            ),
                        },
                        "created_before": {
                            "type": "string",
                            "description": (
                                "ISO date or datetime, inclusive; a bare date "
                                f"includes the whole day. {timestamp_note}"
                            ),
                        },
                        "updated_after": {
                            "type": "string",
                            "description": (
                                f"ISO date or datetime, inclusive. {timestamp_note}"
                            ),
                        },
                        "updated_before": {
                            "type": "string",
                            "description": (
                                "ISO date or datetime, inclusive; a bare date "
                                f"includes the whole day. {timestamp_note}"
                            ),
                        },
                        "page_num": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "0-indexed. Default 0.",
                        },
                        "page_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_PAGE_SIZE,
                            "description": f"Default and max {MAX_PAGE_SIZE}.",
                        },
                    },
                    "required": ["entity_type"],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=CrmListToolStart()))

    def _validate_args(self, llm_kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Returns the entity type and the supplied arguments. A null argument
        counts as omitted."""
        args = {key: value for key, value in llm_kwargs.items() if value is not None}
        reject_unknown_keys(args, ALL_FIELDS, "crm_list arguments")

        entity_type = parse_entity_type(
            args.get("entity_type"), CRM_LIST_ENTITY_TYPES, self.name
        )

        allowed = FILTERS_BY_ENTITY_TYPE[entity_type]
        inapplicable = sorted(
            key for key in args if key not in PAGING_FIELDS and key not in allowed
        )
        if inapplicable:
            raise ToolCallException(
                message=f"Inapplicable filters for {entity_type}: {inapplicable}",
                llm_facing_message=(
                    f"Filter(s) {', '.join(inapplicable)} do not apply to "
                    f"entity_type '{entity_type}'. Filters for {entity_type}: "
                    f"{', '.join(allowed) or 'none'}."
                ),
            )
        return entity_type, args

    def run(
        self,
        placement: Placement,
        override_kwargs: None = None,  # noqa: ARG002
        **llm_kwargs: Any,
    ) -> ToolResponse:
        with stream_tool_call_error(self.emitter, placement, CrmListToolDelta):
            return self._run(placement, llm_kwargs)

    def _run(self, placement: Placement, llm_kwargs: dict[str, Any]) -> ToolResponse:
        entity_type, args = self._validate_args(llm_kwargs)
        page_num, page_size = parse_page(args, self.name)

        with self._session_factory() as db_session:
            if entity_type == "contact":
                payload = self._list_contacts(db_session, args, page_num, page_size)
            elif entity_type == "organization":
                payload = self._list_organizations(
                    db_session, args, page_num, page_size
                )
            elif entity_type == "interaction":
                payload = self._list_interactions(db_session, args, page_num, page_size)
            else:
                payload = self._list_tags(db_session, args, page_num, page_size)

        return crm_tool_response(self.emitter, placement, payload, CrmListToolDelta)

    def _parse_datetime(self, args: dict[str, Any], field: str) -> datetime | None:
        raw = args.get(field)
        if raw is None:
            return None
        if isinstance(raw, str) and not raw.strip():
            raise ToolCallException(
                message=f"Blank {field} in {self.name}",
                llm_facing_message=f"'{field}' must be an ISO date or datetime.",
            )
        dt = parse_datetime_maybe(raw, field)
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _parse_list_filters(self, args: dict[str, Any]) -> dict[str, Any]:
        def _upper(field: str) -> datetime | None:
            dt = self._parse_datetime(args, field)
            # A bare YYYY-MM-DD upper bound covers the whole day (inclusive).
            raw = args.get(field)
            if dt is not None and isinstance(raw, str) and is_date_only(raw):
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt

        sort_by = args.get("sort_by")
        if sort_by is not None:
            sb = str(sort_by).strip().lower()
            if sb not in ("created_at", "updated_at"):
                raise ToolCallException(
                    message=f"Invalid sort_by in {self.name}: {sort_by}",
                    llm_facing_message="'sort_by' must be 'created_at' or 'updated_at'.",
                )
            sort_by = sb

        sort_dir = args.get("sort_dir")
        if sort_dir is not None:
            sd = str(sort_dir).strip().lower()
            if sd not in ("asc", "desc"):
                raise ToolCallException(
                    message=f"Invalid sort_dir in {self.name}: {sort_dir}",
                    llm_facing_message="'sort_dir' must be 'asc' or 'desc'.",
                )
            sort_dir = sd

        return {
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "created_after": self._parse_datetime(args, "created_after"),
            "created_before": _upper("created_before"),
            "updated_after": self._parse_datetime(args, "updated_after"),
            "updated_before": _upper("updated_before"),
        }

    def _parse_tag_ids(self, args: dict[str, Any]) -> list[UUID] | None:
        if "tag_ids" not in args:
            return None
        tag_ids = parse_uuid_list(args["tag_ids"], "tag_ids")
        if not tag_ids:
            raise ToolCallException(
                message=f"Empty tag_ids in {self.name}",
                llm_facing_message=(
                    "'tag_ids' is empty. Omit it to list without a tag filter."
                ),
            )
        return tag_ids

    def _optional_uuid(self, args: dict[str, Any], field: str) -> UUID | None:
        return parse_uuid(args[field], field) if field in args else None

    def _parse_principal(self, args: dict[str, Any]) -> str | None:
        principal = args.get("principal")
        if principal is None:
            return None
        if not isinstance(principal, str) or not principal.strip():
            raise ToolCallException(
                message=f"Invalid principal in {self.name}: {principal!r}",
                llm_facing_message="'principal' must be a non-empty string.",
            )
        return principal.strip()

    def _add_principal_hint(
        self, db_session: Session, payload: dict[str, Any], principal: str | None
    ) -> None:
        """With no results for a principal, list other spellings that may be
        the same official."""
        if principal is None or payload["total_items"] > 0:
            return
        similar = find_similar_principals(db_session, principal)
        if not similar:
            return
        payload["similar_principals"] = [
            {"name": row.name, "contact_count": row.contact_count} for row in similar
        ]
        payload["note"] = (
            "Nothing matches this exact principal spelling. If one of "
            "similar_principals is the same official, list again with that "
            "spelling."
        )

    def _page(
        self,
        entity_type: str,
        page_num: int,
        page_size: int,
        total: int,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "entity_type": entity_type,
            "page_num": page_num,
            "page_size": page_size,
            "total_items": total,
            "results": results,
        }

    def _list_contacts(
        self,
        db_session: Session,
        args: dict[str, Any],
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        status = parse_stage_maybe(
            args.get("status"),
            allowed_stages=self._stage_options,
            field_name="status",
        )
        category_raw = args.get("category")
        category: str | None = None
        if category_raw is not None:
            if not isinstance(category_raw, str) or not category_raw.strip():
                raise ToolCallException(
                    message=f"Invalid category in {self.name}: {category_raw!r}",
                    llm_facing_message="'category' must be a non-empty string.",
                )
            category = category_raw.strip()

        principal = self._parse_principal(args)
        contacts, total = list_contacts(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
            status=status,
            category=category,
            organization_id=self._optional_uuid(args, "organization_id"),
            principal=principal,
            tag_ids=self._parse_tag_ids(args),
            **self._parse_list_filters(args),
        )

        payload = self._page(
            "contact",
            page_num,
            page_size,
            total,
            serialize_contacts(db_session, contacts),
        )
        self._add_principal_hint(db_session, payload, principal)
        return payload

    def _list_organizations(
        self,
        db_session: Session,
        args: dict[str, Any],
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        organizations, total = list_organizations(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
            tag_ids=self._parse_tag_ids(args),
            **self._parse_list_filters(args),
        )
        return self._page(
            "organization",
            page_num,
            page_size,
            total,
            [
                serialize_organization(o, tags=get_organization_tags(o.id, db_session))
                for o in organizations
            ],
        )

    def _list_interactions(
        self,
        db_session: Session,
        args: dict[str, Any],
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        interaction_type = (
            parse_enum_maybe(
                CrmInteractionType, args["interaction_type"], "interaction_type"
            )
            if "interaction_type" in args
            else None
        )
        principal = self._parse_principal(args)
        interactions, total = list_interactions(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
            contact_id=self._optional_uuid(args, "contact_id"),
            organization_id=self._optional_uuid(args, "organization_id"),
            principal=principal,
            interaction_type=interaction_type,
        )
        payload = self._page(
            "interaction",
            page_num,
            page_size,
            total,
            serialize_interactions(db_session, interactions),
        )
        self._add_principal_hint(db_session, payload, principal)
        return payload

    def _list_tags(
        self,
        db_session: Session,
        args: dict[str, Any],  # noqa: ARG002
        page_num: int,
        page_size: int,
    ) -> dict[str, Any]:
        tags, total = list_tags(
            db_session=db_session,
            page_num=page_num,
            page_size=page_size,
        )
        return self._page(
            "tag", page_num, page_size, total, [serialize_tag(t) for t in tags]
        )
