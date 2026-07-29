import json
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.chat.chat_file_utils import build_chat_upload_metadata
from onyx.chat.chat_file_utils import update_chat_upload_file_metadata
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import UserFileStatus
from onyx.db.models import User
from onyx.server.documents.connector import upload_files
from onyx.server.features.projects.projects_file_utils import categorize_uploaded_files
from onyx.server.features.projects.projects_file_utils import get_upload_size_bytes
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/chat/files")


class ChatUploadFileSnapshot(BaseModel):
    id: str
    temp_id: str | None = None
    name: str
    project_id: int | None = None
    user_id: UUID | None
    file_id: str
    created_at: str
    status: UserFileStatus
    last_accessed_at: str | None = None
    file_type: str | None
    chat_file_type: str
    token_count: int | None
    chunk_count: int | None = None


class RejectedChatUpload(BaseModel):
    file_name: str
    reason: str


class ChatUploadResponse(BaseModel):
    user_files: list[ChatUploadFileSnapshot]
    rejected_files: list[RejectedChatUpload]


def _build_hashed_file_key(file: UploadFile) -> str:
    name_prefix = (file.filename or "")[:50]
    return f"{get_upload_size_bytes(file)}|{name_prefix}"


@router.post("/upload", tags=PUBLIC_API_TAGS)
def upload_chat_files(
    files: list[UploadFile] = File(...),
    temp_id_map: str | None = Form(None),
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatUploadResponse:
    try:
        parsed_temp_id_map: dict[str, str] | None = None
        if temp_id_map:
            try:
                parsed = json.loads(temp_id_map)
                if isinstance(parsed, dict):
                    parsed_temp_id_map = {str(k): str(v) for k, v in parsed.items()}
            except json.JSONDecodeError:
                parsed_temp_id_map = None

        categorized_files = categorize_uploaded_files(files, db_session)
        upload_response = upload_files(
            categorized_files.acceptable,
            FileOrigin.CHAT_UPLOAD,
            unzip=False,
        )

        uploaded_files: list[ChatUploadFileSnapshot] = []
        for file_id, file in zip(upload_response.file_paths, categorized_files.acceptable):
            content_type = file.content_type
            token_count = categorized_files.acceptable_file_to_token_count.get(
                file.filename or "",
            )
            file_record = update_chat_upload_file_metadata(
                file_id=file_id,
                metadata=build_chat_upload_metadata(
                    uploaded_by_user_id=user.id,
                    original_content_type=content_type,
                    token_count=token_count,
                ),
                db_session=db_session,
            )
            temp_id = (
                parsed_temp_id_map.get(_build_hashed_file_key(file))
                if parsed_temp_id_map
                else None
            )
            response_content_type = content_type or file_record.file_type
            uploaded_files.append(
                ChatUploadFileSnapshot(
                    id=file_id,
                    temp_id=temp_id,
                    name=file.filename or file_record.display_name,
                    project_id=None,
                    user_id=user.id,
                    file_id=file_id,
                    created_at=file_record.created_at.isoformat(),
                    status=UserFileStatus.COMPLETED,
                    last_accessed_at=file_record.created_at.isoformat(),
                    file_type=response_content_type,
                    chat_file_type=mime_type_to_chat_file_type(
                        response_content_type
                    ).value,
                    token_count=token_count,
                    chunk_count=None,
                )
            )

        db_session.commit()

        return ChatUploadResponse(
            user_files=uploaded_files,
            rejected_files=[
                RejectedChatUpload(
                    file_name=rejected_file.filename,
                    reason=rejected_file.reason,
                )
                for rejected_file in categorized_files.rejected
            ],
        )
    except HTTPException:
        db_session.rollback()
        raise
    except Exception as e:
        db_session.rollback()
        logger.exception("Error uploading chat files - %s: %s", type(e).__name__, e)
        raise HTTPException(
            status_code=500,
            detail="Failed to upload files. Please try again or contact support if the issue persists.",
        )
