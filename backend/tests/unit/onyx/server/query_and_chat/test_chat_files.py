import json
from datetime import datetime
from datetime import timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from fastapi import UploadFile
from starlette.datastructures import Headers

from onyx.configs.constants import FileOrigin
from onyx.db.enums import UserFileStatus
from onyx.file_store.models import ChatFileType
from onyx.server.query_and_chat.chat_files import upload_chat_files


def test_upload_chat_files_disables_zip_expansion_and_preserves_temp_id() -> None:
    upload = UploadFile(
        filename="note.txt",
        file=BytesIO(b"abc"),
        size=None,
        headers=Headers({"content-type": "text/plain"}),
    )
    categorized_files = SimpleNamespace(
        acceptable=[upload],
        rejected=[],
        acceptable_file_to_token_count={"note.txt": 5},
    )
    upload_response = SimpleNamespace(file_paths=["stored-file-1"])
    file_record = SimpleNamespace(
        created_at=datetime(2026, 3, 25, tzinfo=timezone.utc),
        file_type="text/plain",
        display_name="note.txt",
    )
    user_id = uuid4()
    db_session = MagicMock()

    with (
        patch(
            "onyx.server.query_and_chat.chat_files.categorize_uploaded_files",
            return_value=categorized_files,
        ),
        patch(
            "onyx.server.query_and_chat.chat_files.upload_files",
            return_value=upload_response,
        ) as mock_upload_files,
        patch(
            "onyx.server.query_and_chat.chat_files.update_chat_upload_file_metadata",
            return_value=file_record,
        ),
        patch(
            "onyx.server.query_and_chat.chat_files.mime_type_to_chat_file_type",
            return_value=ChatFileType.PLAIN_TEXT,
        ),
    ):
        response = upload_chat_files(
            files=[upload],
            temp_id_map=json.dumps({"3|note.txt": "temp-1"}),
            user=MagicMock(id=user_id),
            db_session=db_session,
        )

    mock_upload_files.assert_called_once_with(
        categorized_files.acceptable,
        FileOrigin.CHAT_UPLOAD,
        unzip=False,
    )
    assert response.rejected_files == []
    assert len(response.user_files) == 1
    assert response.user_files[0].temp_id == "temp-1"
    assert response.user_files[0].status == UserFileStatus.COMPLETED
    db_session.commit.assert_called_once()
