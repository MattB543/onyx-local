"""Regression tests locking in the KMS feature's encryption-aware cache guard.

The custom fork NEVER caches encrypted KV values in the cache backend
(Redis), because the cache is not encrypted at rest. A regression that
re-enabled caching on the encrypted path would leak plaintext secrets into
Redis. These tests assert the guard holds on both the store() and load()
paths, and that the non-encrypted path still caches normally.

These are pure unit tests: the cache backend is mocked, the DB session is
mocked, and the ``KVStore`` ORM model is patched out so the test does not
depend on real AWS KMS / Fernet encryption or a live database.
"""

from contextlib import contextmanager
from typing import Any
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from onyx.key_value_store.store import REDIS_KEY_PREFIX
from onyx.key_value_store.store import PgRedisKVStore


@contextmanager
def _yield_session(session: MagicMock) -> Iterator[MagicMock]:
    yield session


class _FakeKVStore:
    """Lightweight stand-in for the ``KVStore`` ORM model.

    The real model wraps ``encrypted_value`` in an ``EncryptedJson`` column
    whose SQLAlchemy ``set`` event triggers actual encryption (KMS/Fernet)
    and rejects non-dict values. The store-level cache guard under test does
    not care about any of that, so we replace the model with a plain object
    to keep the test hermetic.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.key = kwargs.get("key")
        self.value = kwargs.get("value")
        self.encrypted_value = kwargs.get("encrypted_value")


@pytest.fixture
def patched_store(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[PgRedisKVStore, MagicMock, MagicMock]]:
    """Build a PgRedisKVStore with a mocked cache, mocked DB session, and a
    patched-out KVStore model. Returns (store, cache, db_session)."""
    cache = MagicMock()
    db_session = MagicMock()
    # No existing row by default -> exercises the INSERT branch in store().
    db_session.query.return_value.filter_by.return_value.first.return_value = None

    monkeypatch.setattr(
        "onyx.key_value_store.store.get_session_with_current_tenant",
        lambda: _yield_session(db_session),
    )
    monkeypatch.setattr(
        "onyx.key_value_store.store.KVStore",
        _FakeKVStore,
    )

    store = PgRedisKVStore(cache=cache)
    yield store, cache, db_session


def test_store_encrypted_value_never_calls_cache_set(
    patched_store: tuple[PgRedisKVStore, MagicMock, MagicMock],
) -> None:
    """Storing an encrypted value must NOT write to the cache backend; instead
    it deletes any stale cached entry for that key."""
    store, cache, _ = patched_store

    store.store("api-token", {"secret": "swordfish"}, encrypt=True)

    # The guard: encrypted values are never written to the (unencrypted) cache.
    cache.set.assert_not_called()
    # Defensive invalidation of any pre-existing cached plaintext for this key.
    cache.delete.assert_called_once_with(REDIS_KEY_PREFIX + "api-token")


def test_store_plain_value_is_cached(
    patched_store: tuple[PgRedisKVStore, MagicMock, MagicMock],
) -> None:
    """A non-encrypted value SHOULD be cached, proving the test distinguishes
    the two paths (and isn't trivially passing by never caching anything)."""
    store, cache, _ = patched_store

    store.store("feature-flag", {"enabled": True}, encrypt=False)

    cache.set.assert_called_once()
    cached_key = cache.set.call_args.args[0]
    assert cached_key == REDIS_KEY_PREFIX + "feature-flag"
    cache.delete.assert_not_called()


def test_load_encrypted_value_never_calls_cache_set(
    patched_store: tuple[PgRedisKVStore, MagicMock, MagicMock],
) -> None:
    """Loading an encrypted value must return the decrypted plaintext WITHOUT
    ever caching it; it should evict any stale cache entry instead."""
    store, cache, db_session = patched_store
    cache.get.return_value = None  # force a DB read

    sensitive = MagicMock()
    sensitive.get_value.return_value = {"secret": "swordfish"}
    db_obj = _FakeKVStore(key="api-token", value=None, encrypted_value=sensitive)
    db_session.query.return_value.filter_by.return_value.first.return_value = db_obj

    value = store.load("api-token")

    assert value == {"secret": "swordfish"}
    # Decryption must apply_mask=False (internal backend use).
    sensitive.get_value.assert_called_once_with(apply_mask=False)
    cache.set.assert_not_called()
    cache.delete.assert_called_once_with(REDIS_KEY_PREFIX + "api-token")


def test_load_plain_value_is_cached(
    patched_store: tuple[PgRedisKVStore, MagicMock, MagicMock],
) -> None:
    """Loading a non-encrypted value DOES populate the cache, confirming the
    guard is specific to the encrypted path."""
    store, cache, db_session = patched_store
    cache.get.return_value = None  # force a DB read

    db_obj = _FakeKVStore(key="feature-flag", value={"enabled": True}, encrypted_value=None)
    db_session.query.return_value.filter_by.return_value.first.return_value = db_obj

    value = store.load("feature-flag")

    assert value == {"enabled": True}
    cache.set.assert_called_once()
    cached_key = cache.set.call_args.args[0]
    assert cached_key == REDIS_KEY_PREFIX + "feature-flag"
    cache.delete.assert_not_called()
