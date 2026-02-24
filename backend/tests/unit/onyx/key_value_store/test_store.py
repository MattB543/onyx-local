from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from onyx.key_value_store.store import cleanup_legacy_kv_store_redis_cache
from onyx.key_value_store.store import KV_REDIS_LEGACY_CLEANUP_MARKER_KEY
from onyx.key_value_store.store import PgRedisKVStore


@contextmanager
def _yield_session(session: MagicMock):
    yield session


def test_store_encrypted_value_never_writes_plaintext_to_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = MagicMock()
    db_session = MagicMock()
    db_session.query.return_value.filter_by.return_value.first.return_value = None
    monkeypatch.setattr(
        "onyx.key_value_store.store.get_session_with_current_tenant",
        lambda: _yield_session(db_session),
    )

    kv_store = PgRedisKVStore(redis_client=redis_client)
    kv_store.store("secret-key", "sensitive", encrypt=True)

    redis_client.set.assert_not_called()
    redis_client.delete.assert_called_once()


def test_load_encrypted_value_does_not_cache_plaintext_in_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = MagicMock()
    redis_client.get.return_value = None

    sensitive = MagicMock()
    sensitive.get_value.return_value = {"token": "abc"}
    db_obj = MagicMock()
    db_obj.value = None
    db_obj.encrypted_value = sensitive

    db_session = MagicMock()
    db_session.query.return_value.filter_by.return_value.first.return_value = db_obj
    monkeypatch.setattr(
        "onyx.key_value_store.store.get_session_with_current_tenant",
        lambda: _yield_session(db_session),
    )

    kv_store = PgRedisKVStore(redis_client=redis_client)
    value = kv_store.load("secret-key")

    assert value == {"token": "abc"}
    redis_client.set.assert_not_called()
    redis_client.delete.assert_called_once()


def test_load_plain_value_still_uses_redis_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = MagicMock()
    redis_client.get.return_value = None

    db_obj = MagicMock()
    db_obj.value = {"feature": True}
    db_obj.encrypted_value = None

    db_session = MagicMock()
    db_session.query.return_value.filter_by.return_value.first.return_value = db_obj
    monkeypatch.setattr(
        "onyx.key_value_store.store.get_session_with_current_tenant",
        lambda: _yield_session(db_session),
    )

    kv_store = PgRedisKVStore(redis_client=redis_client)
    value = kv_store.load("plain-key")

    assert value == {"feature": True}
    redis_client.set.assert_called_once()


def test_cleanup_legacy_cache_deletes_prefixed_keys() -> None:
    redis_client = MagicMock()
    redis_client.get.return_value = None
    redis_client.scan_iter.return_value = [b"onyx_kv_store:a", b"onyx_kv_store:b"]
    redis_client.delete.side_effect = [2]

    cleanup_legacy_kv_store_redis_cache(redis_client=redis_client)

    redis_client.scan_iter.assert_called_once_with(match="onyx_kv_store:*")
    redis_client.set.assert_called_once_with(KV_REDIS_LEGACY_CLEANUP_MARKER_KEY, "1")


def test_cleanup_legacy_cache_skips_when_marker_exists() -> None:
    redis_client = MagicMock()
    redis_client.get.return_value = b"1"

    cleanup_legacy_kv_store_redis_cache(redis_client=redis_client)

    redis_client.scan_iter.assert_not_called()
    redis_client.delete.assert_not_called()


def test_delete_commits_db_before_redis_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    redis_client = MagicMock()
    redis_client.delete.side_effect = lambda *_: order.append("redis_delete")

    db_session = MagicMock()
    delete_chain = db_session.query.return_value.filter_by.return_value
    delete_chain.delete.return_value = 1
    db_session.commit.side_effect = lambda: order.append("db_commit")

    monkeypatch.setattr(
        "onyx.key_value_store.store.get_session_with_current_tenant",
        lambda: _yield_session(db_session),
    )

    kv_store = PgRedisKVStore(redis_client=redis_client)
    kv_store.delete("plain-key")

    assert order == ["db_commit", "redis_delete"]
