from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.db.crm import add_interaction_attendees
from onyx.db.crm import add_tag_to_contact
from onyx.db.crm import add_tag_to_organization
from onyx.db.crm import create_contact
from onyx.db.crm import create_interaction
from onyx.db.crm import create_organization
from onyx.db.crm import create_tag
from onyx.db.crm import get_allowed_contact_stages
from onyx.db.crm import get_contact_by_id
from onyx.db.crm import get_contact_owner_ids
from onyx.db.crm import get_contact_tags
from onyx.db.crm import get_interaction_attendees
from onyx.db.crm import get_or_create_crm_settings
from onyx.db.crm import get_organization_by_id
from onyx.db.crm import get_organization_tags
from onyx.db.crm import get_tag_by_id
from onyx.db.crm import list_contacts
from onyx.db.crm import list_interactions
from onyx.db.crm import list_organizations
from onyx.db.crm import list_tags
from onyx.db.crm import remove_tag_from_contact
from onyx.db.crm import remove_tag_from_organization
from onyx.db.crm import search_crm_entities
from onyx.db.crm import update_contact
from onyx.db.crm import update_crm_settings
from onyx.db.crm import update_organization
from onyx.db.crm import validate_stage_string
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import CrmAttendeeRole
from onyx.db.enums import CrmOrganizationType
from onyx.db.models import User
from onyx.server.documents.models import PaginatedReturn
from onyx.server.features.crm.models import CrmContactCreateRequest
from onyx.server.features.crm.models import CrmContactPatchRequest
from onyx.server.features.crm.models import CrmContactSnapshot
from onyx.server.features.crm.models import CrmEntityType
from onyx.server.features.crm.models import CrmInteractionAttendeeSnapshot
from onyx.server.features.crm.models import CrmInteractionCreateRequest
from onyx.server.features.crm.models import CrmInteractionSnapshot
from onyx.server.features.crm.models import CrmOrganizationCreateRequest
from onyx.server.features.crm.models import CrmOrganizationPatchRequest
from onyx.server.features.crm.models import CrmOrganizationSnapshot
from onyx.server.features.crm.models import CrmSearchResultItem
from onyx.server.features.crm.models import CrmSettingsPatchRequest
from onyx.server.features.crm.models import CrmSettingsSnapshot
from onyx.server.features.crm.models import CrmTagCreateRequest
from onyx.server.features.crm.models import CrmTagSnapshot
from onyx.utils.logger import setup_logger


logger = setup_logger()

router = APIRouter(prefix="/user/crm")


def _load_contact_or_404(contact_id: UUID, db_session: Session):
    contact = get_contact_by_id(contact_id, db_session)
    if contact is None:
        raise HTTPException(status_code=404, detail="CRM contact not found.")
    return contact


def _load_organization_or_404(organization_id: UUID, db_session: Session):
    organization = get_organization_by_id(organization_id, db_session)
    if organization is None:
        raise HTTPException(status_code=404, detail="CRM organization not found.")
    return organization


def _load_tag_or_404(tag_id: UUID, db_session: Session):
    tag = get_tag_by_id(tag_id, db_session)
    if tag is None:
        raise HTTPException(status_code=404, detail="CRM tag not found.")
    return tag


def _serialize_contact(contact, db_session: Session) -> CrmContactSnapshot:
    owner_ids = get_contact_owner_ids(contact.id, db_session)
    tags = get_contact_tags(contact.id, db_session)
    return CrmContactSnapshot.from_model(
        contact=contact,
        owner_ids=owner_ids,
        tags=tags,
    )


def _serialize_organization(organization, db_session: Session) -> CrmOrganizationSnapshot:
    tags = get_organization_tags(organization.id, db_session)
    return CrmOrganizationSnapshot.from_model(organization=organization, tags=tags)


def _serialize_interaction(interaction, db_session: Session) -> CrmInteractionSnapshot:
    attendees = get_interaction_attendees(interaction.id, db_session)
    user_name_by_id: dict[UUID, str | None] = {}
    contact_name_by_id: dict[UUID, str | None] = {}
    attendee_snapshots: list[CrmInteractionAttendeeSnapshot] = []

    for attendee in attendees:
        display_name: str | None = None

        if attendee.user_id is not None:
            if attendee.user_id not in user_name_by_id:
                attendee_user = db_session.get(User, attendee.user_id)
                user_name_by_id[attendee.user_id] = (
                    (attendee_user.personal_name or attendee_user.email)
                    if attendee_user
                    else None
                )
            display_name = user_name_by_id[attendee.user_id]

        if attendee.contact_id is not None:
            if attendee.contact_id not in contact_name_by_id:
                attendee_contact = get_contact_by_id(attendee.contact_id, db_session)
                if attendee_contact is None:
                    contact_name_by_id[attendee.contact_id] = None
                else:
                    name_parts = [
                        attendee_contact.first_name,
                        attendee_contact.last_name or "",
                    ]
                    full_name = " ".join(part for part in name_parts if part).strip()
                    contact_name_by_id[attendee.contact_id] = (
                        full_name or attendee_contact.email
                    )
            display_name = contact_name_by_id[attendee.contact_id]

        attendee_snapshots.append(
            CrmInteractionAttendeeSnapshot.from_model(
                attendee=attendee,
                display_name=display_name,
            )
        )

    return CrmInteractionSnapshot.from_model(
        interaction=interaction,
        attendee_snapshots=attendee_snapshots,
    )


def _ensure_user_exists(user_id: UUID, db_session: Session) -> None:
    if db_session.get(User, user_id) is not None:
        return
    raise HTTPException(status_code=404, detail=f"CRM user not found: {user_id}")


@router.get("/settings")
def get_settings(
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> CrmSettingsSnapshot:
    settings = get_or_create_crm_settings(db_session)
    return CrmSettingsSnapshot.from_model(settings)


@router.patch("/settings")
def patch_settings(
    settings_patch_request: CrmSettingsPatchRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_admin_user),
) -> CrmSettingsSnapshot:
    patches = settings_patch_request.model_dump(exclude_unset=True)
    settings = update_crm_settings(
        db_session,
        updated_by=user.id,
        patches=patches,
    )
    return CrmSettingsSnapshot.from_model(settings)


@router.get("/search")
def search_entities(
    q: str = Query("", description="Query text to search in CRM entities."),
    entity_types: list[CrmEntityType] | None = Query(
        None, description="Entity types to include in search."
    ),
    page_num: int = Query(0, ge=0, description="Page number (0-indexed)."),
    page_size: int = Query(25, ge=1, le=200, description="Items per page."),
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> PaginatedReturn[CrmSearchResultItem]:
    requested_entity_types = [entity_type.value for entity_type in entity_types] if entity_types else None
    search_results, total_items = search_crm_entities(
        db_session=db_session,
        query=q,
        entity_types=requested_entity_types,
        page_num=page_num,
        page_size=page_size,
    )

    return PaginatedReturn(
        items=[
            CrmSearchResultItem(
                entity_type=CrmEntityType(result.entity_type),
                entity_id=result.entity_id,
                primary_text=result.primary_text,
                secondary_text=result.secondary_text,
                rank=result.rank,
                sort_at=result.sort_at,
            )
            for result in search_results
        ],
        total_items=total_items,
    )


@router.get("/contacts")
def get_contacts(
    q: str | None = Query(None, description="Optional query filter."),
    status: str | None = Query(
        None,
        description="Filter by CRM contact status.",
    ),
    category: str | None = Query(
        None,
        description="Filter by CRM contact category.",
    ),
    organization_id: UUID | None = Query(
        None, description="Filter by CRM organization."
    ),
    tag_ids: list[UUID] | None = Query(None, description="Filter by tag ids."),
    sort_by: str | None = Query(
        None,
        description="Sort field: 'updated_at' (default) or 'created_at'.",
    ),
    page_num: int = Query(0, ge=0, description="Page number (0-indexed)."),
    page_size: int = Query(25, ge=1, le=200, description="Items per page."),
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> PaginatedReturn[CrmContactSnapshot]:
    normalized_status: str | None = None
    if status is not None:
        allowed_stages = get_allowed_contact_stages(db_session)
        try:
            normalized_status = validate_stage_string(
                status,
                allowed_stages=allowed_stages,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    normalized_category: str | None = None
    if category is not None:
        stripped = category.strip()
        if stripped:
            normalized_category = stripped

    contacts, total_items = list_contacts(
        db_session=db_session,
        page_num=page_num,
        page_size=page_size,
        query=q,
        status=normalized_status,
        category=normalized_category,
        organization_id=organization_id,
        tag_ids=tag_ids,
        sort_by=sort_by,
    )
    return PaginatedReturn(
        items=[_serialize_contact(contact, db_session) for contact in contacts],
        total_items=total_items,
    )


@router.post("/contacts")
def post_contact(
    contact_create_request: CrmContactCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> CrmContactSnapshot:
    if contact_create_request.organization_id:
        _load_organization_or_404(contact_create_request.organization_id, db_session)

    if "owner_ids" in contact_create_request.model_fields_set:
        owner_ids = contact_create_request.owner_ids or []
    else:
        owner_ids = [user.id] if user.id is not None else []

    for owner_uuid in owner_ids:
        _ensure_user_exists(owner_uuid, db_session)

    allowed_stages = get_allowed_contact_stages(db_session)
    requested_status = (
        contact_create_request.status
        if "status" in contact_create_request.model_fields_set
        else allowed_stages[0]
    )
    try:
        normalized_stage = (
            validate_stage_string(
                requested_status,
                allowed_stages=allowed_stages,
            )
            or allowed_stages[0]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    contact, created = create_contact(
        db_session=db_session,
        first_name=contact_create_request.first_name,
        last_name=contact_create_request.last_name,
        email=contact_create_request.email,
        phone=contact_create_request.phone,
        title=contact_create_request.title,
        organization_id=contact_create_request.organization_id,
        owner_ids=owner_ids,
        source=contact_create_request.source,
        status=normalized_stage,
        category=contact_create_request.category,
        notes=contact_create_request.notes,
        linkedin_url=contact_create_request.linkedin_url,
        location=contact_create_request.location,
        created_by=user.id,
    )
    if not created:
        raise HTTPException(
            status_code=409,
            detail="A CRM contact with this email already exists.",
        )
    return _serialize_contact(contact, db_session)


@router.get("/contacts/{contact_id}")
def get_contact(
    contact_id: UUID,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> CrmContactSnapshot:
    contact = _load_contact_or_404(contact_id, db_session)
    return _serialize_contact(contact, db_session)


@router.patch("/contacts/{contact_id}")
def patch_contact(
    contact_id: UUID,
    contact_patch_request: CrmContactPatchRequest,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> CrmContactSnapshot:
    contact = _load_contact_or_404(contact_id, db_session)

    patches = contact_patch_request.model_dump(exclude_unset=True)
    if "organization_id" in patches and patches["organization_id"] is not None:
        _load_organization_or_404(patches["organization_id"], db_session)

    if "status" in patches:
        if patches["status"] is None:
            raise HTTPException(status_code=400, detail="'status' cannot be null.")
        allowed_stages = get_allowed_contact_stages(db_session)
        try:
            patches["status"] = validate_stage_string(
                patches.get("status"),
                allowed_stages=allowed_stages,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if "owner_ids" in patches:
        owner_ids_patch = patches["owner_ids"]
        if owner_ids_patch is None:
            patches["owner_ids"] = []
        else:
            for owner_uuid in owner_ids_patch:
                _ensure_user_exists(owner_uuid, db_session)

    try:
        updated_contact = update_contact(
            db_session=db_session,
            contact=contact,
            patches=patches,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A CRM contact with this email already exists.",
        )
    except ValueError as e:
        message = str(e)
        raise HTTPException(
            status_code=409 if "already exists" in message else 400,
            detail=message,
        )

    return _serialize_contact(updated_contact, db_session)


@router.get("/organizations")
def get_organizations(
    q: str | None = Query(None, description="Optional query filter."),
    type: CrmOrganizationType | None = Query(
        None,
        description="Filter by organization type.",
    ),
    tag_ids: list[UUID] | None = Query(None, description="Filter by tag ids."),
    sort_by: str | None = Query(
        None,
        description="Sort field: 'updated_at' (default) or 'created_at'.",
    ),
    page_num: int = Query(0, ge=0, description="Page number (0-indexed)."),
    page_size: int = Query(25, ge=1, le=200, description="Items per page."),
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> PaginatedReturn[CrmOrganizationSnapshot]:
    organizations, total_items = list_organizations(
        db_session=db_session,
        page_num=page_num,
        page_size=page_size,
        query=q,
        org_type=type,
        tag_ids=tag_ids,
        sort_by=sort_by,
    )
    return PaginatedReturn(
        items=[
            _serialize_organization(organization, db_session)
            for organization in organizations
        ],
        total_items=total_items,
    )


@router.post("/organizations")
def post_organization(
    organization_create_request: CrmOrganizationCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> CrmOrganizationSnapshot:
    organization, created = create_organization(
        db_session=db_session,
        name=organization_create_request.name,
        website=organization_create_request.website,
        type=organization_create_request.type,
        sector=organization_create_request.sector,
        location=organization_create_request.location,
        size=organization_create_request.size,
        notes=organization_create_request.notes,
        created_by=user.id,
    )
    if not created:
        raise HTTPException(
            status_code=409,
            detail="A CRM organization with this name already exists.",
        )
    return _serialize_organization(organization, db_session)


@router.get("/organizations/{organization_id}")
def get_organization(
    organization_id: UUID,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> CrmOrganizationSnapshot:
    organization = _load_organization_or_404(organization_id, db_session)
    return _serialize_organization(organization, db_session)


@router.patch("/organizations/{organization_id}")
def patch_organization(
    organization_id: UUID,
    organization_patch_request: CrmOrganizationPatchRequest,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> CrmOrganizationSnapshot:
    organization = _load_organization_or_404(organization_id, db_session)

    patches = organization_patch_request.model_dump(exclude_unset=True)
    try:
        updated_organization = update_organization(
            db_session=db_session,
            organization=organization,
            patches=patches,
        )
    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="A CRM organization with this name already exists.",
        )
    except ValueError as e:
        message = str(e)
        raise HTTPException(
            status_code=409 if "already exists" in message else 400,
            detail=message,
        )

    return _serialize_organization(updated_organization, db_session)


@router.get("/interactions")
def get_interactions(
    contact_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    page_num: int = Query(0, ge=0, description="Page number (0-indexed)."),
    page_size: int = Query(25, ge=1, le=200, description="Items per page."),
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> PaginatedReturn[CrmInteractionSnapshot]:
    interactions, total_items = list_interactions(
        db_session=db_session,
        page_num=page_num,
        page_size=page_size,
        contact_id=contact_id,
        organization_id=organization_id,
    )

    return PaginatedReturn(
        items=[
            _serialize_interaction(interaction, db_session)
            for interaction in interactions
        ],
        total_items=total_items,
    )


@router.post("/interactions")
def post_interaction(
    interaction_create_request: CrmInteractionCreateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(current_user),
) -> CrmInteractionSnapshot:
    if interaction_create_request.contact_id:
        _load_contact_or_404(interaction_create_request.contact_id, db_session)
    if interaction_create_request.organization_id:
        _load_organization_or_404(interaction_create_request.organization_id, db_session)

    attendees_were_omitted = (
        "attendees" not in interaction_create_request.model_fields_set
    )
    attendee_inputs = interaction_create_request.attendees or []

    # Validate attendee references and collapse duplicate attendees before creating
    # the interaction to avoid partially persisted records.
    deduped_attendees: dict[tuple[UUID | None, UUID | None], CrmAttendeeRole] = {}
    if attendees_were_omitted:
        if user.id is not None:
            deduped_attendees[(user.id, None)] = CrmAttendeeRole.ORGANIZER
        if interaction_create_request.contact_id is not None:
            deduped_attendees[(None, interaction_create_request.contact_id)] = (
                CrmAttendeeRole.ATTENDEE
            )

    for attendee in attendee_inputs:
        if attendee.user_id:
            attendee_user = db_session.get(User, attendee.user_id)
            if attendee_user is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"CRM attendee user not found: {attendee.user_id}",
                )

        if attendee.contact_id:
            attendee_contact = get_contact_by_id(attendee.contact_id, db_session)
            if attendee_contact is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"CRM attendee contact not found: {attendee.contact_id}",
                )

        key = (attendee.user_id, attendee.contact_id)
        existing_role = deduped_attendees.get(key)
        if existing_role is None:
            deduped_attendees[key] = attendee.role
        elif (
            existing_role != CrmAttendeeRole.ORGANIZER
            and attendee.role == CrmAttendeeRole.ORGANIZER
        ):
            deduped_attendees[key] = attendee.role

    try:
        interaction = create_interaction(
            db_session=db_session,
            contact_id=interaction_create_request.contact_id,
            organization_id=interaction_create_request.organization_id,
            logged_by=user.id,
            interaction_type=interaction_create_request.type,
            title=interaction_create_request.title,
            summary=interaction_create_request.summary,
            occurred_at=interaction_create_request.occurred_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    user_ids_by_role: dict[CrmAttendeeRole, list[UUID]] = defaultdict(list)
    contact_ids_by_role: dict[CrmAttendeeRole, list[UUID]] = defaultdict(list)
    for (attendee_user_id, attendee_contact_id), role in deduped_attendees.items():
        if attendee_user_id is not None:
            user_ids_by_role[role].append(attendee_user_id)
        if attendee_contact_id is not None:
            contact_ids_by_role[role].append(attendee_contact_id)

    for role in CrmAttendeeRole:
        if not user_ids_by_role.get(role) and not contact_ids_by_role.get(role):
            continue
        add_interaction_attendees(
            db_session=db_session,
            interaction_id=interaction.id,
            user_ids=user_ids_by_role.get(role),
            contact_ids=contact_ids_by_role.get(role),
            role=role,
        )

    return _serialize_interaction(interaction, db_session)


@router.get("/tags")
def get_tags(
    q: str | None = Query(None, description="Optional query filter."),
    page_num: int = Query(0, ge=0, description="Page number (0-indexed)."),
    page_size: int = Query(25, ge=1, le=200, description="Items per page."),
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> PaginatedReturn[CrmTagSnapshot]:
    tags, total_items = list_tags(
        db_session=db_session,
        page_num=page_num,
        page_size=page_size,
        query=q,
    )
    return PaginatedReturn(
        items=[CrmTagSnapshot.from_model(tag) for tag in tags],
        total_items=total_items,
    )


@router.post("/tags")
def post_tag(
    tag_create_request: CrmTagCreateRequest,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> CrmTagSnapshot:
    tag, created = create_tag(
        db_session=db_session,
        name=tag_create_request.name,
        color=tag_create_request.color,
    )
    if not created:
        raise HTTPException(
            status_code=409,
            detail="A CRM tag with this name already exists.",
        )
    return CrmTagSnapshot.from_model(tag)


@router.post("/contacts/{contact_id}/tags/{tag_id}")
def add_contact_tag(
    contact_id: UUID,
    tag_id: UUID,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> list[CrmTagSnapshot]:
    contact = _load_contact_or_404(contact_id, db_session)
    _ = _load_tag_or_404(tag_id, db_session)

    add_tag_to_contact(db_session=db_session, contact_id=contact.id, tag_id=tag_id)
    return [CrmTagSnapshot.from_model(tag) for tag in get_contact_tags(contact.id, db_session)]


@router.delete("/contacts/{contact_id}/tags/{tag_id}")
def delete_contact_tag(
    contact_id: UUID,
    tag_id: UUID,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> list[CrmTagSnapshot]:
    contact = _load_contact_or_404(contact_id, db_session)
    _ = _load_tag_or_404(tag_id, db_session)

    remove_tag_from_contact(db_session=db_session, contact_id=contact.id, tag_id=tag_id)
    return [CrmTagSnapshot.from_model(tag) for tag in get_contact_tags(contact.id, db_session)]


@router.post("/organizations/{organization_id}/tags/{tag_id}")
def add_organization_tag(
    organization_id: UUID,
    tag_id: UUID,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> list[CrmTagSnapshot]:
    organization = _load_organization_or_404(organization_id, db_session)
    _ = _load_tag_or_404(tag_id, db_session)

    add_tag_to_organization(
        db_session=db_session,
        organization_id=organization.id,
        tag_id=tag_id,
    )
    return [
        CrmTagSnapshot.from_model(tag)
        for tag in get_organization_tags(organization.id, db_session)
    ]


@router.delete("/organizations/{organization_id}/tags/{tag_id}")
def delete_organization_tag(
    organization_id: UUID,
    tag_id: UUID,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> list[CrmTagSnapshot]:
    organization = _load_organization_or_404(organization_id, db_session)
    _ = _load_tag_or_404(tag_id, db_session)

    remove_tag_from_organization(
        db_session=db_session,
        organization_id=organization.id,
        tag_id=tag_id,
    )
    return [
        CrmTagSnapshot.from_model(tag)
        for tag in get_organization_tags(organization.id, db_session)
    ]
