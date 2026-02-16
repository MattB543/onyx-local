from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmContactSource
from onyx.db.enums import CrmContactStatus
from onyx.db.enums import CrmInteractionType
from onyx.db.enums import CrmOrganizationType
from onyx.db.models import CrmContact
from onyx.db.models import CrmInteraction
from onyx.db.models import CrmInteractionAttendee
from onyx.db.models import CrmOrganization
from onyx.db.models import CrmSettings
from onyx.db.models import CrmTag


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
    updated_by: UUID | None
    updated_at: datetime

    @classmethod
    def from_model(cls, settings: CrmSettings) -> "CrmSettingsSnapshot":
        return CrmSettingsSnapshot(
            enabled=settings.enabled,
            tier2_enabled=settings.tier2_enabled,
            tier3_deals=settings.tier3_deals,
            tier3_custom_fields=settings.tier3_custom_fields,
            updated_by=settings.updated_by,
            updated_at=settings.updated_at,
        )


class CrmSettingsPatchRequest(BaseModel):
    enabled: bool | None = None
    tier2_enabled: bool | None = None
    tier3_deals: bool | None = None
    tier3_custom_fields: bool | None = None


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


class CrmContactCreateRequest(BaseModel):
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    organization_id: UUID | None = None
    owner_id: UUID | None = None
    source: CrmContactSource | None = None
    status: CrmContactStatus = CrmContactStatus.LEAD
    notes: str | None = None
    linkedin_url: str | None = None
    location: str | None = None


class CrmContactPatchRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    title: str | None = None
    organization_id: UUID | None = None
    owner_id: UUID | None = None
    source: CrmContactSource | None = None
    status: CrmContactStatus | None = None
    notes: str | None = None
    linkedin_url: str | None = None
    location: str | None = None


class CrmContactSnapshot(BaseModel):
    id: UUID
    first_name: str
    last_name: str | None
    full_name: str
    email: str | None
    phone: str | None
    title: str | None
    organization_id: UUID | None
    owner_id: UUID | None
    source: CrmContactSource | None
    status: CrmContactStatus
    notes: str | None
    linkedin_url: str | None
    location: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    tags: list[CrmTagSnapshot]

    @classmethod
    def from_model(
        cls,
        contact: CrmContact,
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
            owner_id=contact.owner_id,
            source=contact.source,
            status=contact.status,
            notes=contact.notes,
            linkedin_url=contact.linkedin_url,
            location=contact.location,
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
    role: CrmAttendeeRole
    created_at: datetime

    @classmethod
    def from_model(
        cls, attendee: CrmInteractionAttendee
    ) -> "CrmInteractionAttendeeSnapshot":
        return CrmInteractionAttendeeSnapshot(
            id=attendee.id,
            user_id=attendee.user_id,
            contact_id=attendee.contact_id,
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
    attendees: list[CrmInteractionAttendeeInput] = Field(default_factory=list)


class CrmInteractionSnapshot(BaseModel):
    id: UUID
    contact_id: UUID | None
    organization_id: UUID | None
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
        attendees: list[CrmInteractionAttendee] | None = None,
    ) -> "CrmInteractionSnapshot":
        return CrmInteractionSnapshot(
            id=interaction.id,
            contact_id=interaction.contact_id,
            organization_id=interaction.organization_id,
            logged_by=interaction.logged_by,
            type=interaction.type,
            title=interaction.title,
            summary=interaction.summary,
            occurred_at=interaction.occurred_at,
            created_at=interaction.created_at,
            updated_at=interaction.updated_at,
            attendees=[
                CrmInteractionAttendeeSnapshot.from_model(attendee)
                for attendee in (attendees or [])
            ],
        )


class CrmSearchResultItem(BaseModel):
    entity_type: CrmEntityType
    entity_id: str
    primary_text: str
    secondary_text: str | None
    rank: float
    sort_at: datetime | None
