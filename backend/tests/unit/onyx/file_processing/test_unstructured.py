"""The Unstructured API key is an instance secret, so it must live in the
encrypted KV table (``onyx.db.encrypted_kv_store``) and never in the plain KV
store, which mirrors values into Redis in plaintext."""

from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import KV_UNSTRUCTURED_API_KEY
from onyx.file_processing.unstructured import delete_unstructured_api_key
from onyx.file_processing.unstructured import get_unstructured_api_key
from onyx.file_processing.unstructured import update_unstructured_api_key
from onyx.key_value_store.interface import KvKeyNotFoundError


def test_update_unstructured_api_key_uses_encrypted_kv_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert = MagicMock()
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.upsert_encrypted_kv",
        upsert,
    )

    update_unstructured_api_key("test-api-key")

    # The dict wrapper is required: EncryptedJson rejects bare strings.
    upsert.assert_called_once_with(
        KV_UNSTRUCTURED_API_KEY,
        {"value": "test-api-key"},
    )


def test_get_unstructured_api_key_unwraps_stored_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = MagicMock(return_value={"value": "test-api-key"})
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.load_encrypted_kv",
        load,
    )

    assert get_unstructured_api_key() == "test-api-key"
    load.assert_called_once_with(KV_UNSTRUCTURED_API_KEY)


def test_get_unstructured_api_key_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.load_encrypted_kv",
        MagicMock(side_effect=KvKeyNotFoundError),
    )

    assert get_unstructured_api_key() is None


def test_update_then_get_round_trips_through_encrypted_kv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write and read wired to the same fake store, so a mismatch between the
    wrapping in update() and the unwrapping in get() would fail here."""
    fake_table: dict[str, dict[str, str]] = {}

    def _upsert(key: str, value: dict[str, str]) -> None:
        fake_table[key] = value

    def _load(key: str) -> dict[str, str]:
        try:
            return fake_table[key]
        except KeyError:
            raise KvKeyNotFoundError

    monkeypatch.setattr(
        "onyx.file_processing.unstructured.upsert_encrypted_kv", _upsert
    )
    monkeypatch.setattr("onyx.file_processing.unstructured.load_encrypted_kv", _load)

    assert get_unstructured_api_key() is None
    update_unstructured_api_key("test-api-key")
    assert get_unstructured_api_key() == "test-api-key"


def test_delete_unstructured_api_key_uses_encrypted_kv_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete = MagicMock()
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.delete_encrypted_kv",
        delete,
    )

    delete_unstructured_api_key()

    delete.assert_called_once_with(KV_UNSTRUCTURED_API_KEY)


def test_delete_unstructured_api_key_propagates_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matches the pre-relocation contract: deleting an unset key raises."""
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.delete_encrypted_kv",
        MagicMock(side_effect=KvKeyNotFoundError),
    )

    with pytest.raises(KvKeyNotFoundError):
        delete_unstructured_api_key()
