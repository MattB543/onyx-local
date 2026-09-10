"""Blob copies made while forking a chat are cleaned up even when a copy
fails part-way (raw blob saved, plaintext companion not)."""

from io import BytesIO
from unittest.mock import MagicMock, call

import pytest

from onyx.db.chat import _copied_descriptors, _delete_copied_files
from onyx.file_store.models import ChatFileType, FileDescriptor
from onyx.file_store.utils import plaintext_file_name_for_id


def _file_store(fail_on_plaintext: bool) -> MagicMock:
    store = MagicMock()
    store.read_file_record.return_value = MagicMock(
        display_name="notes.txt",
        file_origin="chat_upload",
        file_type="text/plain",
        file_metadata=None,
    )
    store.read_file.return_value.__enter__.return_value = BytesIO(b"x")
    store.has_file.return_value = True
    if fail_on_plaintext:
        store.save_file.side_effect = [None, RuntimeError("plaintext write failed")]
    return store


def test_partial_copy_is_registered_and_cleaned_up() -> None:
    store = _file_store(fail_on_plaintext=True)
    file_map: dict[str, str] = {}
    descriptor: FileDescriptor = {
        "id": "old-id",
        "type": ChatFileType.PLAIN_TEXT,
        "name": "notes.txt",
    }

    with pytest.raises(RuntimeError):
        _copied_descriptors([descriptor], file_map, store)

    # The raw blob was written before the failure; its id must be tracked.
    assert list(file_map) == ["old-id"]
    new_id = file_map["old-id"]
    assert store.save_file.call_args_list[0].kwargs["file_id"] == new_id

    _delete_copied_files(store, file_map)
    assert store.delete_file.call_args_list == [
        call(new_id, error_on_missing=False),
        call(plaintext_file_name_for_id(new_id), error_on_missing=False),
    ]


def test_user_file_descriptors_are_shared_not_copied() -> None:
    store = _file_store(fail_on_plaintext=False)
    file_map: dict[str, str] = {}
    descriptor: FileDescriptor = {
        "id": "old-id",
        "type": ChatFileType.PLAIN_TEXT,
        "name": "notes.txt",
        "user_file_id": "uf-1",
    }

    assert _copied_descriptors([descriptor], file_map, store) == [descriptor]
    assert file_map == {}
    store.save_file.assert_not_called()
