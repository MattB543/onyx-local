"""The Unstructured API key is an instance secret, so it must live in the
encrypted KV table (``onyx.db.encrypted_kv_store``) and never in the plain KV
store, which mirrors values into Redis in plaintext."""

from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import KV_UNSTRUCTURED_API_KEY
from onyx.file_processing.unstructured import (
    delete_unstructured_api_key,
    get_unstructured_api_key,
    update_unstructured_api_key,
)
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
    legacy_store = MagicMock()
    legacy_store.load.side_effect = KvKeyNotFoundError
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )

    assert get_unstructured_api_key() is None


def test_get_unstructured_api_key_read_repairs_legacy_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-KMS deployment may hold the key as a bare string in the plain KV
    store. get() must return it AND migrate it forward to the encrypted table."""
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.load_encrypted_kv",
        MagicMock(side_effect=KvKeyNotFoundError),
    )
    legacy_store = MagicMock()
    legacy_store.load.return_value = "legacy-api-key"
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )
    upsert = MagicMock()
    monkeypatch.setattr("onyx.file_processing.unstructured.upsert_encrypted_kv", upsert)

    assert get_unstructured_api_key() == "legacy-api-key"
    upsert.assert_called_once_with(KV_UNSTRUCTURED_API_KEY, {"value": "legacy-api-key"})
    # The legacy row must be retired, otherwise a later delete only drops the
    # encrypted copy and the next read resurrects the key.
    legacy_store.delete.assert_called_once_with(KV_UNSTRUCTURED_API_KEY)


def test_get_unstructured_api_key_read_repairs_wrapped_legacy_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Some deployments stored the legacy row as {"value": ...} rather than a
    bare string; both shapes must migrate and retire."""
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.load_encrypted_kv",
        MagicMock(side_effect=KvKeyNotFoundError),
    )
    legacy_store = MagicMock()
    legacy_store.load.return_value = {"value": "legacy-api-key"}
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )
    upsert = MagicMock()
    monkeypatch.setattr("onyx.file_processing.unstructured.upsert_encrypted_kv", upsert)

    assert get_unstructured_api_key() == "legacy-api-key"
    upsert.assert_called_once_with(KV_UNSTRUCTURED_API_KEY, {"value": "legacy-api-key"})
    legacy_store.delete.assert_called_once_with(KV_UNSTRUCTURED_API_KEY)


def test_get_unstructured_api_key_migration_tolerates_missing_legacy_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent delete of the legacy row must not fail the migration."""
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.load_encrypted_kv",
        MagicMock(side_effect=KvKeyNotFoundError),
    )
    legacy_store = MagicMock()
    legacy_store.load.return_value = "legacy-api-key"
    legacy_store.delete.side_effect = KvKeyNotFoundError
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.upsert_encrypted_kv", MagicMock()
    )

    assert get_unstructured_api_key() == "legacy-api-key"


def test_get_unstructured_api_key_ignores_malformed_legacy_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.load_encrypted_kv",
        MagicMock(side_effect=KvKeyNotFoundError),
    )
    legacy_store = MagicMock()
    legacy_store.load.return_value = {"unexpected": "shape"}
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )
    upsert = MagicMock()
    monkeypatch.setattr("onyx.file_processing.unstructured.upsert_encrypted_kv", upsert)

    assert get_unstructured_api_key() is None
    upsert.assert_not_called()


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
    legacy_store = MagicMock()
    legacy_store.load.side_effect = KvKeyNotFoundError
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )

    assert get_unstructured_api_key() is None
    update_unstructured_api_key("test-api-key")
    assert get_unstructured_api_key() == "test-api-key"


def test_delete_unstructured_api_key_removes_both_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete = MagicMock()
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.delete_encrypted_kv",
        delete,
    )
    legacy_store = MagicMock()
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )

    delete_unstructured_api_key()

    delete.assert_called_once_with(KV_UNSTRUCTURED_API_KEY)
    legacy_store.delete.assert_called_once_with(KV_UNSTRUCTURED_API_KEY)


def test_delete_unstructured_api_key_tolerates_missing_legacy_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy cleanup is best-effort; only the encrypted row is contractual."""
    delete = MagicMock()
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.delete_encrypted_kv",
        delete,
    )
    legacy_store = MagicMock()
    legacy_store.delete.side_effect = KvKeyNotFoundError
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
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
    legacy_store = MagicMock()
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )

    with pytest.raises(KvKeyNotFoundError):
        delete_unstructured_api_key()

    # The legacy row is still retired, so a missing encrypted row cannot leave a
    # plaintext key behind for the next read to resurrect.
    legacy_store.delete.assert_called_once_with(KV_UNSTRUCTURED_API_KEY)


def test_delete_then_get_does_not_resurrect_legacy_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end against fake stores: once deleted, the key stays gone."""
    encrypted_table: dict[str, dict[str, str]] = {}
    legacy_table: dict[str, str] = {KV_UNSTRUCTURED_API_KEY: "legacy-api-key"}

    def _upsert(key: str, value: dict[str, str]) -> None:
        encrypted_table[key] = value

    def _load(key: str) -> dict[str, str]:
        try:
            return encrypted_table[key]
        except KeyError:
            raise KvKeyNotFoundError

    def _delete_encrypted(key: str) -> None:
        try:
            del encrypted_table[key]
        except KeyError:
            raise KvKeyNotFoundError

    def _legacy_load(key: str) -> str:
        try:
            return legacy_table[key]
        except KeyError:
            raise KvKeyNotFoundError

    def _legacy_delete(key: str) -> None:
        try:
            del legacy_table[key]
        except KeyError:
            raise KvKeyNotFoundError

    legacy_store = MagicMock()
    legacy_store.load.side_effect = _legacy_load
    legacy_store.delete.side_effect = _legacy_delete

    monkeypatch.setattr(
        "onyx.file_processing.unstructured.upsert_encrypted_kv", _upsert
    )
    monkeypatch.setattr("onyx.file_processing.unstructured.load_encrypted_kv", _load)
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.delete_encrypted_kv", _delete_encrypted
    )
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        MagicMock(return_value=legacy_store),
    )

    # First read migrates the legacy row forward and retires it.
    assert get_unstructured_api_key() == "legacy-api-key"
    assert legacy_table == {}

    delete_unstructured_api_key()

    assert encrypted_table == {}
    assert get_unstructured_api_key() is None
