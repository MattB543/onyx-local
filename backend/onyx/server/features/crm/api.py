from __future__ import annotations

from collections import defaultdict
from datetime import date
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import UploadFile
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.db.crm import add_interaction_attendees
from onyx.db.crm import add_tag_to_contact
from onyx.db.crm import add_tag_to_organization
from onyx.db.crm import build_contact_email_lookup
from onyx.db.crm import build_org_name_lookup
from onyx.db.crm import build_user_email_lookup
from onyx.db.crm import create_contact
from onyx.db.crm import create_interaction
from onyx.db.crm import create_organization
from onyx.db.crm import create_tag
from onyx.db.crm import ensure_tags_exist
from onyx.db.crm import export_all_contacts
from onyx.db.crm import export_all_interactions
from onyx.db.crm import export_all_organizations
from onyx.db.crm import get_allowed_contact_stages
from onyx.db.crm import get_contact_by_id
from onyx.db.crm import get_contact_owner_ids
from onyx.db.crm import get_contact_tags
from onyx.db.crm import get_interaction_attendees
from onyx.db.crm import get_or_create_crm_settings
from onyx.db.crm import get_organization_by_id
from onyx.db.crm import get_organization_by_name
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
from onyx.db.enums import CrmContactSource
from onyx.db.enums import CrmInteractionType
from onyx.db.enums import CrmOrganizationType
from onyx.db.models import CrmContact
from onyx.db.models import CrmOrganization
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.configs.app_configs import USER_FILE_MAX_UPLOAD_SIZE_MB
from onyx.configs.app_configs import USER_FILE_MAX_UPLOAD_SIZE_BYTES
from onyx.configs.constants import FileOrigin
from onyx.server.documents.models import PaginatedReturn
from onyx.server.features.crm.csv_utils import build_csv_bytes
from onyx.server.features.crm.csv_utils import CONTACT_CSV_HEADERS
from onyx.server.features.crm.csv_utils import CONTACT_IMPORT_HEADERS
from onyx.server.features.crm.csv_utils import INTERACTION_CSV_HEADERS
from onyx.server.features.crm.csv_utils import INTERACTION_IMPORT_HEADERS
from onyx.server.features.crm.csv_utils import MAX_IMPORT_FILE_SIZE
from onyx.server.features.crm.csv_utils import MAX_IMPORT_ROWS
from onyx.server.features.crm.csv_utils import ORGANIZATION_CSV_HEADERS
from onyx.server.features.crm.csv_utils import ORGANIZATION_IMPORT_HEADERS
from onyx.server.features.crm.csv_utils import parse_csv_upload
from onyx.server.features.crm.csv_utils import parse_datetime_or_none
from onyx.server.features.crm.csv_utils import parse_enum_or_none
from onyx.server.features.crm.csv_utils import parse_pipe_delimited
from onyx.server.features.crm.models import CrmContactCreateRequest
from onyx.server.features.crm.models import CrmContactPatchRequest
from onyx.server.features.crm.models import CrmContactSnapshot
from onyx.server.features.crm.models import CrmEntityType
from onyx.server.features.crm.models import CrmImportError
from onyx.server.features.crm.models import CrmImportResult
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
from onyx.server.features.projects.projects_file_utils import is_upload_too_large
from onyx.utils.logger import setup_logger


logger = setup_logger()

router = APIRouter(prefix="/user/crm")


def _load_contact_or_404(contact_id: UUID, db_session: Session):
    contact = get_contact_by_id(contact_id, db_session)
    if contact is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "CRM contact not found.")
    return contact


def _load_organization_or_404(organization_id: UUID, db_session: Session):
    organization = get_organization_by_id(organization_id, db_session)
    if organization is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "CRM organization not found.")
    return organization


def _load_tag_or_404(tag_id: UUID, db_session: Session):
    tag = get_tag_by_id(tag_id, db_session)
    if tag is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "CRM tag not found.")
    return tag


def _serialize_contact(contact, db_session: Session) -> CrmContactSnapshot:
    owner_ids = get_contact_owner_ids(contact.id, db_session)
    tags = get_contact_tags(contact.id, db_session)
    organization_name: str | None = None
    if contact.organization_id is not None:
        organization = get_organization_by_id(contact.organization_id, db_session)
        if organization is not None:
            organization_name = organization.name
    return CrmContactSnapshot.from_model(
        contact=contact,
        owner_ids=owner_ids,
        organization_name=organization_name,
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
    interaction_contact_name: str | None = None
    interaction_organization_name: str | None = None

    if interaction.contact_id is not None:
        interaction_contact = get_contact_by_id(interaction.contact_id, db_session)
        if interaction_contact is not None:
            name_parts = [
                interaction_contact.first_name,
                interaction_contact.last_name or "",
            ]
            full_name = " ".join(part for part in name_parts if part).strip()
            interaction_contact_name = full_name or interaction_contact.email

    if interaction.organization_id is not None:
        interaction_organization = get_organization_by_id(
            interaction.organization_id, db_session
        )
        if interaction_organization is not None:
            interaction_organization_name = interaction_organization.name

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
        contact_name=interaction_contact_name,
        organization_name=interaction_organization_name,
        attendee_snapshots=attendee_snapshots,
    )


def _ensure_user_exists(user_id: UUID, db_session: Session) -> None:
    if db_session.get(User, user_id) is not None:
        return
    raise OnyxError(OnyxErrorCode.NOT_FOUND, f"CRM user not found: {user_id}")


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
            raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

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
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

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
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            "A CRM contact with this email already exists.",
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
            raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "'status' cannot be null.")
        allowed_stages = get_allowed_contact_stages(db_session)
        try:
            patches["status"] = validate_stage_string(
                patches.get("status"),
                allowed_stages=allowed_stages,
            )
        except ValueError as e:
            raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    if "owner_ids" in patches:
        owner_ids_patch = patches["owner_ids"]
        if owner_ids_patch is None:
            patches["owner_ids"] = []
        else:
            for owner_uuid in owner_ids_patch:
                _ensure_user_exists(owner_uuid, db_session)

    try:
        updated_contact, _ = update_contact(
            db_session=db_session,
            contact=contact,
            patches=patches,
        )
    except IntegrityError:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            "A CRM contact with this email already exists.",
        )
    except ValueError as e:
        message = str(e)
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE if "already exists" in message else OnyxErrorCode.VALIDATION_ERROR,
            message,
        )

    return _serialize_contact(updated_contact, db_session)


@router.post("/contacts/{contact_id}/upload-profile-picture")
def upload_contact_profile_picture(
    contact_id: UUID,
    file: UploadFile,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> dict[str, str]:
    contact = _load_contact_or_404(contact_id, db_session)

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not content_type or not content_type.startswith("image/"):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Only image uploads are supported for CRM profile pictures.",
        )

    if is_upload_too_large(file, USER_FILE_MAX_UPLOAD_SIZE_BYTES):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Profile picture exceeds the maximum allowed size of {USER_FILE_MAX_UPLOAD_SIZE_MB} MB.",
        )

    file_store = get_default_file_store()
    file_id = file_store.save_file(
        content=file.file,
        display_name=file.filename or f"crm_profile_{contact_id}",
        file_origin=FileOrigin.CRM_UPLOAD,
        file_type=content_type,
    )
    update_contact(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": file_id},
    )
    return {"file_id": file_id}


@router.delete("/contacts/{contact_id}/profile-picture")
def delete_contact_profile_picture(
    contact_id: UUID,
    db_session: Session = Depends(get_session),
    _user: User = Depends(current_user),
) -> Response:
    contact = _load_contact_or_404(contact_id, db_session)
    update_contact(
        db_session=db_session,
        contact=contact,
        patches={"profile_picture_file_id": None},
    )
    return Response(status_code=204)


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
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            "A CRM organization with this name already exists.",
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
        updated_organization, _ = update_organization(
            db_session=db_session,
            organization=organization,
            patches=patches,
        )
    except IntegrityError:
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            "A CRM organization with this name already exists.",
        )
    except ValueError as e:
        message = str(e)
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE if "already exists" in message else OnyxErrorCode.VALIDATION_ERROR,
            message,
        )

    return _serialize_organization(updated_organization, db_session)


@router.get("/interactions")
def get_interactions(
    contact_id: UUID | None = Query(None),
    organization_id: UUID | None = Query(None),
    interaction_type: CrmInteractionType | None = Query(None),
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
        interaction_type=interaction_type,
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
                raise OnyxError(
                    OnyxErrorCode.NOT_FOUND,
                    f"CRM attendee user not found: {attendee.user_id}",
                )

        if attendee.contact_id:
            attendee_contact = get_contact_by_id(attendee.contact_id, db_session)
            if attendee_contact is None:
                raise OnyxError(
                    OnyxErrorCode.NOT_FOUND,
                    f"CRM attendee contact not found: {attendee.contact_id}",
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
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

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
        raise OnyxError(
            OnyxErrorCode.DUPLICATE_RESOURCE,
            "A CRM tag with this name already exists.",
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


# ---------------------------------------------------------------------------
# CSV Export endpoints
# ---------------------------------------------------------------------------


@router.get("/export/organizations")
def export_organizations_csv(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    rows = export_all_organizations(db_session)
    csv_bytes = build_csv_bytes(ORGANIZATION_CSV_HEADERS, rows)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="crm_organizations_{date.today().isoformat()}.csv"'
        },
    )


@router.get("/export/contacts")
def export_contacts_csv(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    rows = export_all_contacts(db_session)
    csv_bytes = build_csv_bytes(CONTACT_CSV_HEADERS, rows)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="crm_contacts_{date.today().isoformat()}.csv"'
        },
    )


@router.get("/export/interactions")
def export_interactions_csv(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:
    rows = export_all_interactions(db_session)
    csv_bytes = build_csv_bytes(INTERACTION_CSV_HEADERS, rows)
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="crm_interactions_{date.today().isoformat()}.csv"'
        },
    )


# ---------------------------------------------------------------------------
# CSV Import endpoints
# ---------------------------------------------------------------------------


@router.post("/import/organizations")
async def import_organizations_csv(
    file: UploadFile,
    dry_run: bool = False,
    user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CrmImportResult:
    contents = await file.read()
    if len(contents) > MAX_IMPORT_FILE_SIZE:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Import file exceeds maximum allowed size.",
        )

    try:
        rows = parse_csv_upload(
            contents,
            ORGANIZATION_IMPORT_HEADERS,
            optional_headers=["id", "created_by", "created_at", "updated_at"],
            max_rows=MAX_IMPORT_ROWS,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    result = CrmImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            with db_session.begin_nested():
                name = row.get("name", "").strip()
                if not name:
                    raise ValueError("Organization name is required")

                org_type = parse_enum_or_none(row.get("type", ""), CrmOrganizationType)
                tag_names = parse_pipe_delimited(row.get("tags", ""))

                patches: dict = {
                    "name": name,
                    "website": row.get("website", "").strip() or None,
                    "type": org_type,
                    "sector": row.get("sector", "").strip() or None,
                    "location": row.get("location", "").strip() or None,
                    "size": row.get("size", "").strip() or None,
                    "notes": row.get("notes", "").strip() or None,
                }

                row_id = row.get("id", "").strip()
                resolved_org_id: UUID | None = None
                is_update = False
                anything_changed = False

                if row_id:
                    org = db_session.get(CrmOrganization, UUID(row_id))
                    if not org:
                        raise ValueError(
                            f"Organization with id '{row_id}' not found"
                        )
                    _, org_changed = update_organization(
                        db_session, organization=org, patches=patches, commit=False
                    )
                    resolved_org_id = org.id
                    is_update = True
                    anything_changed = org_changed
                else:
                    existing = get_organization_by_name(name, db_session)
                    if existing:
                        _, org_changed = update_organization(
                            db_session,
                            organization=existing,
                            patches=patches,
                            commit=False,
                        )
                        resolved_org_id = existing.id
                        is_update = True
                        anything_changed = org_changed
                    else:
                        new_org, _ = create_organization(
                            db_session,
                            name=name,
                            website=patches["website"],
                            type=org_type,
                            sector=patches["sector"],
                            location=patches["location"],
                            size=patches["size"],
                            notes=patches["notes"],
                            created_by=user.id if user else None,
                            commit=False,
                        )
                        resolved_org_id = new_org.id
                        result.created += 1

                if resolved_org_id:
                    # Sync tags: replace existing with CSV-declared state
                    desired_tag_map = (
                        ensure_tags_exist(db_session, tag_names, commit=False)
                        if tag_names
                        else {}
                    )
                    desired_tag_ids = set(desired_tag_map.values())

                    # Get current tags on this org
                    db_session.flush()
                    current_tags = get_organization_tags(resolved_org_id, db_session)
                    current_tag_ids = {t.id for t in current_tags}

                    tags_to_remove = current_tag_ids - desired_tag_ids
                    tags_to_add = desired_tag_ids - current_tag_ids

                    for old_tag_id in tags_to_remove:
                        remove_tag_from_organization(
                            db_session,
                            organization_id=resolved_org_id,
                            tag_id=old_tag_id,
                            commit=False,
                        )

                    for new_tag_id in tags_to_add:
                        add_tag_to_organization(
                            db_session,
                            organization_id=resolved_org_id,
                            tag_id=new_tag_id,
                            commit=False,
                        )

                    if tags_to_remove or tags_to_add:
                        anything_changed = True

                if is_update and anything_changed:
                    result.updated += 1
                elif is_update:
                    result.skipped += 1

                db_session.flush()
        except Exception as e:
            result.errors.append(CrmImportError(row=row_num, error=str(e)))

    if dry_run:
        db_session.rollback()
    else:
        db_session.commit()

    return result


@router.post("/import/contacts")
async def import_contacts_csv(
    file: UploadFile,
    dry_run: bool = False,
    user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CrmImportResult:
    contents = await file.read()
    if len(contents) > MAX_IMPORT_FILE_SIZE:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Import file exceeds maximum allowed size.",
        )

    try:
        rows = parse_csv_upload(
            contents,
            CONTACT_IMPORT_HEADERS,
            optional_headers=["id", "created_by", "created_at", "updated_at"],
            max_rows=MAX_IMPORT_ROWS,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    org_name_lookup = build_org_name_lookup(db_session)
    contact_email_lookup = build_contact_email_lookup(db_session)
    user_email_lookup = build_user_email_lookup(db_session)
    allowed_stages = get_allowed_contact_stages(db_session)
    default_stage = allowed_stages[0] if allowed_stages else "new"

    result = CrmImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            with db_session.begin_nested():
                first_name = row.get("first_name", "").strip()
                if not first_name:
                    raise ValueError("Contact first_name is required")

                last_name = row.get("last_name", "").strip() or None
                email = row.get("email", "").strip() or None
                phone = row.get("phone", "").strip() or None
                title = row.get("title", "").strip() or None
                notes = row.get("notes", "").strip() or None
                linkedin_url = row.get("linkedin_url", "").strip() or None
                location = row.get("location", "").strip() or None
                category = row.get("category", "").strip() or None

                # Resolve organization
                org_name = row.get("organization_name", "").strip()
                organization_id: UUID | None = None
                if org_name:
                    organization_id = org_name_lookup.get(org_name.lower())
                    if organization_id is None:
                        raise ValueError(
                            f"Organization '{org_name}' not found"
                        )

                # Resolve owner emails
                owner_email_strs = parse_pipe_delimited(row.get("owner_emails", ""))
                owner_ids: list[UUID] = []
                for owner_email in owner_email_strs:
                    uid = user_email_lookup.get(owner_email.lower())
                    if uid is None:
                        result.errors.append(
                            CrmImportError(
                                row=row_num,
                                error=f"Owner email '{owner_email}' not found (skipped owner)",
                            )
                        )
                    else:
                        owner_ids.append(uid)

                # Validate source
                source = parse_enum_or_none(
                    row.get("source", ""), CrmContactSource
                )

                # Validate status
                status_str = row.get("status", "").strip()
                if status_str:
                    try:
                        status = validate_stage_string(
                            status_str, allowed_stages=allowed_stages
                        )
                    except ValueError:
                        raise ValueError(
                            f"Invalid status '{status_str}'. "
                            f"Allowed: {', '.join(allowed_stages)}"
                        )
                else:
                    status = default_stage

                tag_names = parse_pipe_delimited(row.get("tags", ""))

                patches: dict = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "phone": phone,
                    "title": title,
                    "organization_id": organization_id,
                    "owner_ids": owner_ids,
                    "source": source,
                    "status": status,
                    "category": category,
                    "notes": notes,
                    "linkedin_url": linkedin_url,
                    "location": location,
                }

                row_id = row.get("id", "").strip()
                contact_id: UUID | None = None
                is_update = False
                anything_changed = False

                if row_id:
                    contact = db_session.get(CrmContact, UUID(row_id))
                    if not contact:
                        raise ValueError(
                            f"Contact with id '{row_id}' not found"
                        )
                    _, contact_changed = update_contact(
                        db_session,
                        contact=contact,
                        patches=patches,
                        commit=False,
                    )
                    contact_id = contact.id
                    is_update = True
                    anything_changed = contact_changed
                else:
                    # Dedup by email
                    existing_contact_id = contact_email_lookup.get(email.lower()) if email else None
                    existing = db_session.get(CrmContact, existing_contact_id) if existing_contact_id else None
                    if existing:
                        _, contact_changed = update_contact(
                            db_session,
                            contact=existing,
                            patches=patches,
                            commit=False,
                        )
                        contact_id = existing.id
                        is_update = True
                        anything_changed = contact_changed
                    else:
                        new_contact, _ = create_contact(
                            db_session,
                            first_name=first_name,
                            last_name=last_name,
                            email=email,
                            phone=phone,
                            title=title,
                            organization_id=organization_id,
                            owner_ids=owner_ids,
                            source=source,
                            status=status,
                            category=category,
                            notes=notes,
                            linkedin_url=linkedin_url,
                            location=location,
                            created_by=user.id if user else None,
                            commit=False,
                        )
                        contact_id = new_contact.id
                        if email:
                            contact_email_lookup[email.lower()] = new_contact.id
                        result.created += 1

                if contact_id:
                    desired_tag_map = (
                        ensure_tags_exist(db_session, tag_names, commit=False)
                        if tag_names
                        else {}
                    )
                    desired_tag_ids = set(desired_tag_map.values())

                    current_tags = get_contact_tags(contact_id, db_session)
                    current_tag_ids = {t.id for t in current_tags}

                    tags_to_remove = current_tag_ids - desired_tag_ids
                    tags_to_add = desired_tag_ids - current_tag_ids

                    for old_tag_id in tags_to_remove:
                        remove_tag_from_contact(
                            db_session,
                            contact_id=contact_id,
                            tag_id=old_tag_id,
                            commit=False,
                        )

                    for new_tag_id in tags_to_add:
                        add_tag_to_contact(
                            db_session,
                            contact_id=contact_id,
                            tag_id=new_tag_id,
                            commit=False,
                        )

                    if tags_to_remove or tags_to_add:
                        anything_changed = True

                if is_update and anything_changed:
                    result.updated += 1
                elif is_update:
                    result.skipped += 1

                db_session.flush()
        except Exception as e:
            result.errors.append(CrmImportError(row=row_num, error=str(e)))

    if dry_run:
        db_session.rollback()
    else:
        db_session.commit()

    return result


@router.post("/import/interactions")
async def import_interactions_csv(
    file: UploadFile,
    dry_run: bool = False,
    user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> CrmImportResult:
    contents = await file.read()
    if len(contents) > MAX_IMPORT_FILE_SIZE:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Import file exceeds maximum allowed size.",
        )

    try:
        rows = parse_csv_upload(
            contents,
            INTERACTION_IMPORT_HEADERS,
            optional_headers=["id", "logged_by", "created_at", "updated_at"],
            max_rows=MAX_IMPORT_ROWS,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e))

    org_name_lookup = build_org_name_lookup(db_session)
    contact_email_lookup = build_contact_email_lookup(db_session)
    user_email_lookup = build_user_email_lookup(db_session)

    result = CrmImportResult()

    for row_num, row in enumerate(rows, start=2):
        try:
            with db_session.begin_nested():
                # Validate required fields
                title = row.get("title", "").strip()
                if not title:
                    raise ValueError("Interaction title is required")

                interaction_type = parse_enum_or_none(
                    row.get("type", ""), CrmInteractionType
                )
                if interaction_type is None:
                    raise ValueError("Interaction type is required")

                summary = row.get("summary", "").strip() or None

                # Resolve contact_email -> contact_id
                contact_email = row.get("contact_email", "").strip()
                contact_id: UUID | None = None
                if contact_email:
                    contact_id = contact_email_lookup.get(contact_email.lower())
                    if contact_id is None:
                        raise ValueError(
                            f"Contact with email '{contact_email}' not found"
                        )

                # Resolve organization_name -> organization_id
                org_name = row.get("organization_name", "").strip()
                organization_id: UUID | None = None
                if org_name:
                    organization_id = org_name_lookup.get(org_name.lower())
                    if organization_id is None:
                        raise ValueError(
                            f"Organization '{org_name}' not found"
                        )

                # Parse occurred_at
                occurred_at = parse_datetime_or_none(row.get("occurred_at", ""))

                # Check for update vs create
                row_id = row.get("id", "").strip()
                if row_id:
                    result.skipped += 1
                    result.errors.append(
                        CrmImportError(
                            row=row_num,
                            error="Interaction updates not supported, skipping row with id",
                        )
                    )
                    continue

                interaction = create_interaction(
                    db_session,
                    contact_id=contact_id,
                    organization_id=organization_id,
                    logged_by=user.id if user else None,
                    interaction_type=interaction_type,
                    title=title,
                    summary=summary,
                    occurred_at=occurred_at,
                    commit=False,
                )
                db_session.flush()

                # Parse and add attendees
                organizer_user_emails = parse_pipe_delimited(
                    row.get("organizer_users", "")
                )
                organizer_contact_emails = parse_pipe_delimited(
                    row.get("organizer_contacts", "")
                )
                attendee_user_emails = parse_pipe_delimited(
                    row.get("attendee_users", "")
                )
                attendee_contact_emails = parse_pipe_delimited(
                    row.get("attendee_contacts", "")
                )

                # Organizer users
                org_user_ids: list[UUID] = []
                for email in organizer_user_emails:
                    uid = user_email_lookup.get(email.lower())
                    if uid is None:
                        result.errors.append(
                            CrmImportError(
                                row=row_num,
                                error=f"Organizer user email '{email}' not found (skipped attendee)",
                            )
                        )
                    else:
                        org_user_ids.append(uid)

                # Organizer contacts
                org_contact_ids: list[UUID] = []
                for email in organizer_contact_emails:
                    cid = contact_email_lookup.get(email.lower())
                    if cid is None:
                        result.errors.append(
                            CrmImportError(
                                row=row_num,
                                error=f"Organizer contact email '{email}' not found (skipped attendee)",
                            )
                        )
                    else:
                        org_contact_ids.append(cid)

                # Attendee users
                att_user_ids: list[UUID] = []
                for email in attendee_user_emails:
                    uid = user_email_lookup.get(email.lower())
                    if uid is None:
                        result.errors.append(
                            CrmImportError(
                                row=row_num,
                                error=f"Attendee user email '{email}' not found (skipped attendee)",
                            )
                        )
                    else:
                        att_user_ids.append(uid)

                # Attendee contacts
                att_contact_ids: list[UUID] = []
                for email in attendee_contact_emails:
                    cid = contact_email_lookup.get(email.lower())
                    if cid is None:
                        result.errors.append(
                            CrmImportError(
                                row=row_num,
                                error=f"Attendee contact email '{email}' not found (skipped attendee)",
                            )
                        )
                    else:
                        att_contact_ids.append(cid)

                # Add organizer attendees
                if org_user_ids or org_contact_ids:
                    add_interaction_attendees(
                        db_session=db_session,
                        interaction_id=interaction.id,
                        user_ids=org_user_ids or None,
                        contact_ids=org_contact_ids or None,
                        role=CrmAttendeeRole.ORGANIZER,
                        commit=False,
                    )

                # Add attendee attendees
                if att_user_ids or att_contact_ids:
                    add_interaction_attendees(
                        db_session=db_session,
                        interaction_id=interaction.id,
                        user_ids=att_user_ids or None,
                        contact_ids=att_contact_ids or None,
                        role=CrmAttendeeRole.ATTENDEE,
                        commit=False,
                    )

                result.created += 1
                db_session.flush()
        except Exception as e:
            result.errors.append(CrmImportError(row=row_num, error=str(e)))

    if dry_run:
        db_session.rollback()
    else:
        db_session.commit()

    return result
