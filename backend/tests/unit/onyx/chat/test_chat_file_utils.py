from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.chat.chat_file_utils import (
    build_chat_upload_metadata,
    enqueue_promoted_user_file_indexing,
    promote_chat_uploads_to_user_files,
)
from onyx.configs.constants import FileOrigin
from onyx.db.models import FileRecord, UserFile
from onyx.file_store.models import ChatFileType
from onyx.file_store.utils import verify_user_files


def test_promote_chat_uploads_to_user_files_reuses_existing_user_file() -> None:
    user_id = uuid4()
    existing_user_file = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id="raw-file-1",
        name="contract.pdf",
        file_type="application/pdf",
    )
    db_session = MagicMock(spec=Session)
    db_session.query.return_value.filter.return_value.first.return_value = (
        existing_user_file
    )

    with patch(
        "onyx.chat.chat_file_utils.get_chat_upload_file_record",
        return_value=FileRecord(
            file_id="raw-file-1",
            display_name="contract.pdf",
            file_origin=FileOrigin.CHAT_UPLOAD,
            file_type="application/pdf",
            bucket_name="bucket",
            object_key="object",
        ),
    ):
        result = promote_chat_uploads_to_user_files(
            file_ids=["raw-file-1"],
            user=MagicMock(id=user_id),
            db_session=db_session,
        )

    assert result.raw_file_id_to_user_file_id == {
        "raw-file-1": str(existing_user_file.id)
    }
    assert result.new_user_file_ids == []
    db_session.add.assert_not_called()


def test_promote_chat_uploads_to_user_files_creates_new_user_file() -> None:
    user_id = uuid4()
    db_session = MagicMock(spec=Session)
    db_session.query.return_value.filter.return_value.first.return_value = None
    file_record = FileRecord(
        file_id="raw-file-1",
        display_name="contract.pdf",
        file_origin=FileOrigin.CHAT_UPLOAD,
        file_type="text/plain",
        bucket_name="bucket",
        object_key="object",
        file_metadata=build_chat_upload_metadata(
            uploaded_by_user_id=user_id,
            original_content_type="application/pdf",
            token_count=123,
        ),
    )

    with patch(
        "onyx.chat.chat_file_utils.get_chat_upload_file_record",
        return_value=file_record,
    ):
        result = promote_chat_uploads_to_user_files(
            file_ids=["raw-file-1"],
            user=MagicMock(id=user_id),
            db_session=db_session,
        )

    added_user_file = db_session.add.call_args.args[0]
    assert isinstance(added_user_file, UserFile)
    assert added_user_file.id is not None
    assert added_user_file.user_id == user_id
    assert added_user_file.file_id == "raw-file-1"
    assert added_user_file.name == "contract.pdf"
    assert added_user_file.token_count == 123
    assert added_user_file.content_type == "application/pdf"
    assert added_user_file.file_type == "application/pdf"
    assert result.raw_file_id_to_user_file_id == {
        "raw-file-1": str(added_user_file.id)
    }
    assert result.new_user_file_ids == [added_user_file.id]


def test_promote_chat_uploads_to_user_files_rejects_wrong_owner() -> None:
    db_session = MagicMock(spec=Session)

    with patch(
        "onyx.chat.chat_file_utils.get_chat_upload_file_record",
        return_value=None,
    ):
        try:
            promote_chat_uploads_to_user_files(
                file_ids=["raw-file-1"],
                user=MagicMock(id=uuid4()),
                db_session=db_session,
            )
            raise AssertionError("Expected ValueError for unauthorized chat upload")
        except ValueError as e:
            assert "not a valid chat upload" in str(e)


def test_verify_user_files_allows_raw_chat_upload_without_project() -> None:
    db_session = MagicMock(spec=Session)

    with patch(
        "onyx.file_store.utils.get_chat_upload_file_record",
        return_value=MagicMock(),
    ):
        verify_user_files(
            user_files=[
                {
                    "id": "raw-file-1",
                    "type": ChatFileType.DOC,
                    "name": "contract.pdf",
                }
            ],
            user_id=uuid4(),
            db_session=db_session,
            project_id=None,
        )


def test_verify_user_files_falls_back_to_raw_upload_when_user_file_is_missing() -> None:
    db_session = MagicMock(spec=Session)
    db_session.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "onyx.file_store.utils.get_chat_upload_file_record",
        return_value=MagicMock(),
    ):
        verify_user_files(
            user_files=[
                {
                    "id": "raw-file-1",
                    "type": ChatFileType.DOC,
                    "name": "contract.pdf",
                    "user_file_id": str(uuid4()),
                }
            ],
            user_id=uuid4(),
            db_session=db_session,
            project_id=None,
        )


def test_verify_user_files_rejects_wrong_user_file_owner() -> None:
    owner_id = uuid4()
    other_user_id = uuid4()
    db_session = MagicMock(spec=Session)
    db_session.query.return_value.filter.return_value.first.return_value = UserFile(
        id=uuid4(),
        user_id=owner_id,
        file_id="raw-file-1",
        name="contract.pdf",
        file_type="application/pdf",
    )

    try:
        verify_user_files(
            user_files=[
                {
                    "id": "raw-file-1",
                    "type": ChatFileType.DOC,
                    "name": "contract.pdf",
                    "user_file_id": str(uuid4()),
                }
            ],
            user_id=other_user_id,
            db_session=db_session,
            project_id=None,
        )
        raise AssertionError("Expected ValueError for wrong owner")
    except ValueError as e:
        assert "does not have access to file" in str(e)


def test_verify_user_files_rejects_unknown_non_project_file() -> None:
    db_session = MagicMock(spec=Session)
    db_session.query.return_value.filter.return_value.first.return_value = None

    with patch(
        "onyx.file_store.utils.get_chat_upload_file_record",
        return_value=None,
    ):
        try:
            verify_user_files(
                user_files=[
                    {
                        "id": "missing-file",
                        "type": ChatFileType.DOC,
                        "name": "contract.pdf",
                    }
                ],
                user_id=uuid4(),
                db_session=db_session,
                project_id=None,
            )
            raise AssertionError("Expected ValueError for missing non-project file")
        except ValueError as e:
            assert "no project_id specified" in str(e)


def test_enqueue_promoted_user_file_indexing_serializes_uuid_to_string() -> None:
    user_file_id = uuid4()

    with (
        patch("onyx.chat.chat_file_utils.DISABLE_VECTOR_DB", False),
        patch(
            "onyx.background.celery.versioned_apps.client.app.send_task",
            return_value=MagicMock(id="task-1"),
        ) as mock_send_task,
    ):
        enqueue_promoted_user_file_indexing(
            user_file_ids=[user_file_id],
            tenant_id="tenant-id",
        )

    assert mock_send_task.call_args.kwargs["kwargs"]["user_file_id"] == str(
        user_file_id
    )
