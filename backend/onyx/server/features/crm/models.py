from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmContactSource
from onyx.db.enums import CrmInteractionType
from onyx.db.enums import CrmOrganizationType
from onyx.db.models import CrmContact
from onyx.db.models import CrmInteraction
from onyx.db.models import CrmInteractionAttendee
from onyx.db.models import CrmOrganization
from onyx.db.models import CrmSettings
from onyx.db.models import CrmTag
from onyx.file_store.utils import build_frontend_file_url


class CrmEntityType(str, Enum):
    CONTACT = "contact"
    ORGANIZATION = "organization"
    INTERACTION = "interaction"
    TAG = "tag"


class CrmSettingsSnapshot(BaseModel):
    enabled: bool
    tier2_enabled: bool
    tier3_deals: bool
    tier3_custom_fields: bool
    contact_stage_options: list[str]
    contact_category_suggestions: list[str]
    updated_by: UUID | None
    updated_at: datetime

    @classmethod
    def from_model(cls, settings: CrmSettings) -> "CrmSettingsSnapshot":
        return CrmSettingsSnapshot(
            enabled=settings.enabled,
            tier2_enabled=settings.tier2_enabled,
            tier3_deals=settings.tier3_deals,
            tier3_custom_fields=settings.tier3_custom_fields,
            contact_stage_options=settings.contact_stage_options,
            contact_category_suggestions=settings.contact_category_suggestions,
            updated_by=settings.updated_by,
            updated_at=settings.updated_at,
        )


class CrmSettingsPatchRequest(BaseModel):
    enabled: bool | None = None
    tier2_enabled: bool | None = None
    tier3_deals: bool | None = None
    tier3_custom_fields: bool | None = None
    contact_stage_options: list[str] | None = None
    contact_category_suggestions: list[str] | None = None


class CrmTagSnapshot(BaseModel):
    id: UUID
    name: str
    color: str | None
    created_at: datetime

    @classmethod
    def from_model(cls, tag: CrmTag) -> "CrmTagSnapshot":
        return CrmTagSnapshot(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            created_at=tag.created_at,
        )


class CrmTagCreateRequest(BaseModel):
    name: str
    color: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_contain_pipe(cls, v: str) -> str:
        v = v.strip()
        if "|" in v:
            raise ValueError("Tag names cannot contain the '|' character.")
        return v


class CrmContactCreateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    organization_id: UUID | None = None
    owner_ids: list[UUID] | None = None
    source: CrmContactSource | None = None
    status: str = "lead"
    category: str | None = None
    party_affiliation: str | None = None
    us_state: str | None = None
    principal: str | None = None
    notes: str | None = None
    linkedin_url: str | None = None
    location: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_name(self) -> "CrmContactCreateRequest":
        if not (self.first_name and self.first_name.strip()) and not (
            self.last_name and self.last_name.strip()
        ):
            raise ValueError(
                "A contact requires at least a first name or a last name."
            )
        return self


class CrmContactPatchRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    organization_id: UUID | None = None
    owner_ids: list[UUID] | None = None
    source: CrmContactSource | None = None
    status: str | None = None
    category: str | None = None
    party_affiliation: str | None = None
    us_state: str | None = None
    principal: str | None = None
    notes: str | None = None
    linkedin_url: str | None = None
    location: str | None = None


class CrmContactSnapshot(BaseModel):
    id: UUID
    first_name: str | None
    last_name: str | None
    full_name: str
    email: str | None
    phone: str | None
    title: str | None
    organization_id: UUID | None
    organization_name: str | None
    owner_ids: list[UUID]
    source: CrmContactSource | None
    status: str
    category: str | None
    party_affiliation: str | None
    us_state: str | None
    principal: str | None
    notes: str | None
    linkedin_url: str | None
    location: str | None
    profile_picture_file_id: str | None
    profile_picture_url: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    tags: list[CrmTagSnapshot]

    @classmethod
    def from_model(
        cls,
        contact: CrmContact,
        owner_ids: list[UUID],
        organization_name: str | None = None,
        tags: list[CrmTag] | None = None,
    ) -> "CrmContactSnapshot":
        name_parts = [contact.first_name, contact.last_name or ""]
        full_name = " ".join(part for part in name_parts if part).strip()
        return CrmContactSnapshot(
            id=contact.id,
            first_name=contact.first_name,
            last_name=contact.last_name,
            full_name=full_name,
            email=contact.email,
            phone=contact.phone,
            title=contact.title,
            organization_id=contact.organization_id,
            organization_name=organization_name,
            owner_ids=owner_ids,
            source=contact.source,
            status=contact.status,
            category=contact.category,
            party_affiliation=contact.party_affiliation,
            us_state=contact.us_state,
            principal=contact.principal,
            notes=contact.notes,
            linkedin_url=contact.linkedin_url,
            location=contact.location,
            profile_picture_file_id=contact.profile_picture_file_id,
            profile_picture_url=(
                build_frontend_file_url(contact.profile_picture_file_id)
                if contact.profile_picture_file_id
                else None
            ),
            created_by=contact.created_by,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
            tags=[CrmTagSnapshot.from_model(tag) for tag in (tags or [])],
        )


class CrmOrganizationCreateRequest(BaseModel):
    name: str
    website: str | None = None
    type: CrmOrganizationType | None = None
    sector: str | None = None
    location: str | None = None
    size: str | None = None
    notes: str | None = None


class CrmOrganizationPatchRequest(BaseModel):
    name: str | None = None
    website: str | None = None
    type: CrmOrganizationType | None = None
    sector: str | None = None
    location: str | None = None
    size: str | None = None
    notes: str | None = None


class CrmOrganizationSnapshot(BaseModel):
    id: UUID
    name: str
    website: str | None
    type: CrmOrganizationType | None
    sector: str | None
    location: str | None
    size: str | None
    notes: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    tags: list[CrmTagSnapshot]

    @classmethod
    def from_model(
        cls,
        organization: CrmOrganization,
        tags: list[CrmTag] | None = None,
    ) -> "CrmOrganizationSnapshot":
        return CrmOrganizationSnapshot(
            id=organization.id,
            name=organization.name,
            website=organization.website,
            type=organization.type,
            sector=organization.sector,
            location=organization.location,
            size=organization.size,
            notes=organization.notes,
            created_by=organization.created_by,
            created_at=organization.created_at,
            updated_at=organization.updated_at,
            tags=[CrmTagSnapshot.from_model(tag) for tag in (tags or [])],
        )


class CrmInteractionAttendeeInput(BaseModel):
    user_id: UUID | None = None
    contact_id: UUID | None = None
    role: CrmAttendeeRole = CrmAttendeeRole.ATTENDEE

    @model_validator(mode="after")
    def validate_target(self) -> "CrmInteractionAttendeeInput":
        if bool(self.user_id) == bool(self.contact_id):
            raise ValueError(
                "Exactly one of 'user_id' or 'contact_id' must be provided."
            )
        return self


class CrmInteractionAttendeeSnapshot(BaseModel):
    id: int
    user_id: UUID | None
    contact_id: UUID | None
    display_name: str | None = None
    role: CrmAttendeeRole
    created_at: datetime

    @classmethod
    def from_model(
        cls, attendee: CrmInteractionAttendee, display_name: str | None = None
    ) -> "CrmInteractionAttendeeSnapshot":
        return CrmInteractionAttendeeSnapshot(
            id=attendee.id,
            user_id=attendee.user_id,
            contact_id=attendee.contact_id,
            display_name=display_name,
            role=attendee.role,
            created_at=attendee.created_at,
        )


class CrmInteractionCreateRequest(BaseModel):
    contact_id: UUID | None = None
    organization_id: UUID | None = None
    type: CrmInteractionType
    title: str
    summary: str | None = None
    occurred_at: datetime | None = None
    attendees: list[CrmInteractionAttendeeInput] | None = Field(default=None)


class CrmInteractionPatchRequest(BaseModel):
    contact_id: UUID | None = None
    organization_id: UUID | None = None
    type: CrmInteractionType | None = None
    title: str | None = None
    summary: str | None = None
    occurred_at: datetime | None = None
    attendees: list[CrmInteractionAttendeeInput] | None = None


class CrmInteractionSnapshot(BaseModel):
    id: UUID
    contact_id: UUID | None
    contact_name: str | None
    organization_id: UUID | None
    organization_name: str | None
    logged_by: UUID | None
    type: CrmInteractionType
    title: str
    summary: str | None
    occurred_at: datetime | None
    created_at: datetime
    updated_at: datetime
    attendees: list[CrmInteractionAttendeeSnapshot]

    @classmethod
    def from_model(
        cls,
        interaction: CrmInteraction,
        contact_name: str | None = None,
        organization_name: str | None = None,
        attendees: list[CrmInteractionAttendee] | None = None,
        attendee_snapshots: list[CrmInteractionAttendeeSnapshot] | None = None,
    ) -> "CrmInteractionSnapshot":
        resolved_attendees = attendee_snapshots
        if resolved_attendees is None:
            resolved_attendees = [
                CrmInteractionAttendeeSnapshot.from_model(attendee)
                for attendee in (attendees or [])
            ]

        return CrmInteractionSnapshot(
            id=interaction.id,
            contact_id=interaction.contact_id,
            contact_name=contact_name,
            organization_id=interaction.organization_id,
            organization_name=organization_name,
            logged_by=interaction.logged_by,
            type=interaction.type,
            title=interaction.title,
            summary=interaction.summary,
            occurred_at=interaction.occurred_at,
            created_at=interaction.created_at,
            updated_at=interaction.updated_at,
            attendees=resolved_attendees,
        )


class CrmImportError(BaseModel):
    row: int
    error: str


class CrmImportResult(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[CrmImportError] = []


class CrmSearchResultItem(BaseModel):
    entity_type: CrmEntityType
    entity_id: str
    primary_text: str
    secondary_text: str | None
    rank: float
    sort_at: datetime | None
