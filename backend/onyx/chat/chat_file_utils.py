import datetime
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import (
    CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
    FileOrigin,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.db.llm import fetch_default_llm_model
from onyx.db.models import FileRecord, User, UserFile
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_in_background

logger = setup_logger()

CHAT_UPLOAD_KIND = "user_attachment"
CHAT_UPLOAD_KIND_METADATA_KEY = "chat_upload_kind"
CHAT_UPLOAD_OWNER_ID_METADATA_KEY = "uploaded_by_user_id"
CHAT_UPLOAD_ORIGINAL_CONTENT_TYPE_METADATA_KEY = "original_content_type"
CHAT_UPLOAD_TOKEN_COUNT_METADATA_KEY = "token_count"


@dataclass
class PromotionResult:
    raw_file_id_to_user_file_id: dict[str, str]
    new_user_file_ids: list[UUID]


def _metadata_to_dict(metadata: Any) -> dict[str, Any]:
    return dict(metadata or {})


def _coerce_metadata_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def build_chat_upload_metadata(
    *,
    uploaded_by_user_id: UUID | None,
    original_content_type: str | None,
    token_count: int | None,
) -> dict[str, Any]:
    return {
        CHAT_UPLOAD_KIND_METADATA_KEY: CHAT_UPLOAD_KIND,
        CHAT_UPLOAD_OWNER_ID_METADATA_KEY: (
            str(uploaded_by_user_id) if uploaded_by_user_id is not None else None
        ),
        CHAT_UPLOAD_ORIGINAL_CONTENT_TYPE_METADATA_KEY: original_content_type,
        CHAT_UPLOAD_TOKEN_COUNT_METADATA_KEY: token_count,
    }


def update_chat_upload_file_metadata(
    *,
    file_id: str,
    metadata: dict[str, Any],
    db_session: Session,
) -> FileRecord:
    file_record = (
        db_session.query(FileRecord).filter(FileRecord.file_id == file_id).first()
    )
    if file_record is None:
        raise ValueError(f"File {file_id} was not found after upload")

    existing_metadata = _metadata_to_dict(file_record.file_metadata)
    existing_metadata.update(metadata)
    file_record.file_metadata = existing_metadata
    db_session.flush()
    return file_record


def is_chat_upload_owned_by_user(
    *,
    file_record: FileRecord,
    user_id: UUID | None,
) -> bool:
    if file_record.file_origin != FileOrigin.CHAT_UPLOAD:
        return False

    metadata = _metadata_to_dict(file_record.file_metadata)
    if metadata.get(CHAT_UPLOAD_KIND_METADATA_KEY) != CHAT_UPLOAD_KIND:
        return False

    uploaded_by_user_id = metadata.get(CHAT_UPLOAD_OWNER_ID_METADATA_KEY)
    if user_id is None:
        return uploaded_by_user_id is None

    return str(uploaded_by_user_id) == str(user_id)


def get_chat_upload_file_record(
    *,
    file_id: str,
    user_id: UUID | None,
    db_session: Session,
) -> FileRecord | None:
    file_record = (
        db_session.query(FileRecord).filter(FileRecord.file_id == file_id).first()
    )
    if file_record is None:
        return None

    if not is_chat_upload_owned_by_user(file_record=file_record, user_id=user_id):
        return None

    return file_record


def get_chat_upload_token_count_from_record(file_record: FileRecord) -> int | None:
    metadata = _metadata_to_dict(file_record.file_metadata)
    return _coerce_metadata_int(metadata.get(CHAT_UPLOAD_TOKEN_COUNT_METADATA_KEY))


def get_chat_upload_token_count(
    *,
    file_id: str,
    db_session: Session,
) -> int | None:
    file_record = (
        db_session.query(FileRecord).filter(FileRecord.file_id == file_id).first()
    )
    if file_record is None:
        return None
    return get_chat_upload_token_count_from_record(file_record)


def estimate_token_count_for_text(
    *,
    text: str,
    db_session: Session,
) -> int:
    default_model = fetch_default_llm_model(db_session)
    model_name = default_model.name if default_model else None
    provider_type = default_model.llm_provider.provider if default_model else None
    tokenizer = get_tokenizer(model_name=model_name, provider_type=provider_type)
    return len(tokenizer.encode(text))


def promote_chat_uploads_to_user_files(
    *,
    file_ids: list[str],
    user: User,
    db_session: Session,
) -> PromotionResult:
    raw_file_id_to_user_file_id: dict[str, str] = {}
    new_user_file_ids: list[UUID] = []

    for file_id in dict.fromkeys(file_ids):
        file_record = get_chat_upload_file_record(
            file_id=file_id,
            user_id=user.id,
            db_session=db_session,
        )
        if file_record is None:
            raise ValueError(
                f"File {file_id} is not a valid chat upload for the current user"
            )

        existing_user_file = (
            db_session.query(UserFile)
            .filter(UserFile.user_id == user.id, UserFile.file_id == file_id)
            .first()
        )
        if existing_user_file is not None:
            raw_file_id_to_user_file_id[file_id] = str(existing_user_file.id)
            continue

        metadata = _metadata_to_dict(file_record.file_metadata)
        content_type = metadata.get(CHAT_UPLOAD_ORIGINAL_CONTENT_TYPE_METADATA_KEY)
        if not isinstance(content_type, str) or not content_type:
            content_type = file_record.file_type

        user_file = UserFile(
            id=uuid4(),
            user_id=user.id,
            file_id=file_id,
            name=file_record.display_name or file_id,
            token_count=get_chat_upload_token_count_from_record(file_record),
            content_type=content_type,
            file_type=content_type,
            last_accessed_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add(user_file)
        db_session.flush()

        raw_file_id_to_user_file_id[file_id] = str(user_file.id)
        new_user_file_ids.append(user_file.id)

    return PromotionResult(
        raw_file_id_to_user_file_id=raw_file_id_to_user_file_id,
        new_user_file_ids=new_user_file_ids,
    )


def enqueue_promoted_user_file_indexing(
    *,
    user_file_ids: list[UUID],
    tenant_id: str,
) -> None:
    if not user_file_ids:
        return

    if DISABLE_VECTOR_DB:
        from onyx.background.task_utils import drain_processing_loop

        run_in_background(drain_processing_loop, tenant_id)
        for user_file_id in user_file_ids:
            logger.info(
                "Queued in-process processing for promoted user_file_id=%s",
                user_file_id,
            )
        return

    from onyx.background.celery.versioned_apps.client import app as client_app

    for user_file_id in user_file_ids:
        task = client_app.send_task(
            OnyxCeleryTask.PROCESS_SINGLE_USER_FILE,
            kwargs={"user_file_id": str(user_file_id), "tenant_id": tenant_id},
            queue=OnyxCeleryQueues.USER_FILE_PROCESSING,
            priority=OnyxCeleryPriority.HIGH,
            expires=CELERY_USER_FILE_PROCESSING_TASK_EXPIRES,
        )
        logger.info(
            "Triggered indexing for promoted user_file_id=%s with task_id=%s",
            user_file_id,
            task.id,
        )
