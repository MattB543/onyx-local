from unittest.mock import MagicMock
from unittest.mock import call
from unittest.mock import patch
from uuid import uuid4

from onyx.db.chat import delete_messages_and_files_from_chat_session


def test_delete_messages_and_files_from_chat_session_preserves_promoted_files() -> None:
    chat_session_id = uuid4()
    db_session = MagicMock()
    db_session.execute.return_value.tuples.return_value.all.return_value = [
        (
            1,
            [
                {"id": "raw-chat-only"},
                {"id": "promoted-raw-file"},
                {"id": "already-user-file", "user_file_id": str(uuid4())},
            ],
        )
    ]
    db_session.scalars.return_value.all.return_value = ["promoted-raw-file"]
    file_store = MagicMock()

    with (
        patch("onyx.db.chat.get_default_file_store", return_value=file_store),
        patch("onyx.db.chat.delete_orphaned_search_docs") as mock_delete_orphaned,
    ):
        delete_messages_and_files_from_chat_session(chat_session_id, db_session)

    file_store.delete_file.assert_has_calls(
        [
            call(file_id="raw-chat-only", error_on_missing=False),
            call(file_id="plaintext_raw-chat-only", error_on_missing=False),
        ]
    )
    assert (
        call(file_id="promoted-raw-file", error_on_missing=False)
        not in file_store.delete_file.call_args_list
    )
    assert (
        call(file_id="plaintext_promoted-raw-file", error_on_missing=False)
        not in file_store.delete_file.call_args_list
    )
    db_session.commit.assert_called_once()
    mock_delete_orphaned.assert_called_once_with(db_session)
