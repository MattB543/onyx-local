import json
from typing import cast

from redis.client import Redis

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import KVStore
from onyx.key_value_store.interface import KeyValueStore
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()


REDIS_KEY_PREFIX = "onyx_kv_store:"
KV_REDIS_KEY_EXPIRATION = 60 * 60 * 24  # 1 Day
KV_REDIS_LEGACY_CLEANUP_MARKER_KEY = "onyx_kv_store_cleanup_v2_done"
_REDIS_DELETE_BATCH_SIZE = 256


def cleanup_legacy_kv_store_redis_cache(redis_client: Redis | None = None) -> None:
    """
    Remove pre-upgrade KV Redis entries that may contain plaintext for encrypted values.
    This runs at startup and marks completion in Redis to avoid repeated scans.
    """
    client = redis_client if redis_client is not None else get_redis_client()

    try:
        if client.get(KV_REDIS_LEGACY_CLEANUP_MARKER_KEY):
            return
    except Exception as e:
        logger.error("Failed to read KV Redis cleanup marker: %s", str(e))
        return

    deleted_count = 0
    keys_to_delete: list[bytes | str] = []
    try:
        for redis_key in client.scan_iter(match=f"{REDIS_KEY_PREFIX}*"):
            if not isinstance(redis_key, (bytes, str)):
                continue
            keys_to_delete.append(redis_key)
            if len(keys_to_delete) >= _REDIS_DELETE_BATCH_SIZE:
                deleted_count += client.delete(*keys_to_delete)
                keys_to_delete = []

        if keys_to_delete:
            deleted_count += client.delete(*keys_to_delete)

        client.set(KV_REDIS_LEGACY_CLEANUP_MARKER_KEY, "1")
        logger.notice(
            "Completed legacy KV Redis cleanup; deleted %s key(s).",
            deleted_count,
        )
    except Exception as e:
        logger.error("Failed to clean up legacy KV Redis cache: %s", str(e))


class PgRedisKVStore(KeyValueStore):
    def __init__(self, redis_client: Redis | None = None) -> None:
        # If no redis_client is provided, fall back to the context var
        if redis_client is not None:
            self.redis_client = redis_client
        else:
            self.redis_client = get_redis_client()

    def store(self, key: str, val: JSON_ro, encrypt: bool = False) -> None:
        redis_key = REDIS_KEY_PREFIX + key

        encrypted_val = val if encrypt else None
        plain_val = val if not encrypt else None
        with get_session_with_current_tenant() as db_session:
            obj = db_session.query(KVStore).filter_by(key=key).first()
            if obj:
                obj.value = plain_val
                obj.encrypted_value = encrypted_val  # type: ignore[assignment]
            else:
                obj = KVStore(key=key, value=plain_val, encrypted_value=encrypted_val)
                db_session.query(KVStore).filter_by(key=key).delete()  # just in case
                db_session.add(obj)
            db_session.commit()

        if encrypt:
            # Never cache decrypted encrypted values in Redis.
            try:
                self.redis_client.delete(redis_key)
            except Exception as e:
                logger.error(
                    f"Failed to delete Redis value for encrypted key '{key}': {str(e)}"
                )
        else:
            try:
                self.redis_client.set(
                    redis_key, json.dumps(val), ex=KV_REDIS_KEY_EXPIRATION
                )
            except Exception as e:
                # Fallback gracefully to Postgres if Redis fails
                logger.error(f"Failed to set value in Redis for key '{key}': {str(e)}")

    def load(self, key: str, refresh_cache: bool = False) -> JSON_ro:
        redis_key = REDIS_KEY_PREFIX + key
        if not refresh_cache:
            try:
                redis_value = self.redis_client.get(redis_key)
                if redis_value:
                    if not isinstance(redis_value, bytes):
                        raise ValueError(
                            f"Redis value for key '{key}' is not a bytes object"
                        )
                    return json.loads(redis_value.decode("utf-8"))
            except Exception as e:
                logger.error(
                    f"Failed to get value from Redis for key '{key}': {str(e)}"
                )

        with get_session_with_current_tenant() as db_session:
            obj = db_session.query(KVStore).filter_by(key=key).first()
            if not obj:
                raise KvKeyNotFoundError

            if obj.value is not None:
                value = obj.value
                should_cache_in_redis = True
            elif obj.encrypted_value is not None:
                # Unwrap SensitiveValue - this is internal backend use
                value = obj.encrypted_value.get_value(apply_mask=False)
                should_cache_in_redis = False
            else:
                value = None
                should_cache_in_redis = True

            if should_cache_in_redis:
                try:
                    self.redis_client.set(
                        redis_key,
                        json.dumps(value),
                        ex=KV_REDIS_KEY_EXPIRATION,
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to set value in Redis for key '{key}': {str(e)}"
                    )
            else:
                try:
                    self.redis_client.delete(redis_key)
                except Exception as e:
                    logger.error(
                        f"Failed to delete Redis value for encrypted key '{key}': {str(e)}"
                    )

            return cast(JSON_ro, value)

    def delete(self, key: str) -> None:
        with get_session_with_current_tenant() as db_session:
            result = db_session.query(KVStore).filter_by(key=key).delete()
            if result == 0:
                raise KvKeyNotFoundError
            db_session.commit()

        try:
            self.redis_client.delete(REDIS_KEY_PREFIX + key)
        except Exception as e:
            logger.error(f"Failed to delete value from Redis for key '{key}': {str(e)}")
