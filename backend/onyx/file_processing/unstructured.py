from typing import Any
from typing import IO
from typing import TYPE_CHECKING

from onyx.configs.constants import KV_UNSTRUCTURED_API_KEY
from onyx.db.encrypted_kv_store import delete_encrypted_kv
from onyx.db.encrypted_kv_store import load_encrypted_kv
from onyx.db.encrypted_kv_store import upsert_encrypted_kv
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.key_value_store.interface import unwrap_str
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from unstructured_client.models import operations


logger = setup_logger()


def get_unstructured_api_key() -> str | None:
    try:
        return unwrap_str(load_encrypted_kv(KV_UNSTRUCTURED_API_KEY))
    except KvKeyNotFoundError:
        pass

    # Legacy read-repair: before the encrypted_key_value_store table existed, the
    # key lived in key_value_store (as a bare string on pre-KMS deployments).
    # Migrate it forward on first read so the legacy row is no longer load-bearing
    # by the time upstream drops KVStore.encrypted_value.
    try:
        legacy = get_kv_store().load(KV_UNSTRUCTURED_API_KEY)
    except KvKeyNotFoundError:
        return None
    api_key = legacy.get("value") if isinstance(legacy, dict) else legacy
    if not isinstance(api_key, str) or not api_key:
        return None
    upsert_encrypted_kv(KV_UNSTRUCTURED_API_KEY, {"value": api_key})
    return api_key


def update_unstructured_api_key(api_key: str) -> None:
    # EncryptedJson only accepts dicts, so the raw key is wrapped under "value".
    upsert_encrypted_kv(KV_UNSTRUCTURED_API_KEY, {"value": api_key})


def delete_unstructured_api_key() -> None:
    # Propagates KvKeyNotFoundError when unset, matching the previous KV-store
    # backed behavior that callers rely on.
    delete_encrypted_kv(KV_UNSTRUCTURED_API_KEY)


def _sdk_partition_request(
    file: IO[Any], file_name: str, **kwargs: Any
) -> "operations.PartitionRequest":
    from unstructured_client.models import operations
    from unstructured_client.models import shared

    file.seek(0, 0)
    try:
        request = operations.PartitionRequest(
            partition_parameters=shared.PartitionParameters(
                files=shared.Files(content=file.read(), file_name=file_name),
                **kwargs,
            ),
        )
        return request
    except Exception as e:
        logger.error(
            "Error creating partition request for file %s: %s", file_name, str(e)
        )
        raise


def unstructured_to_text(file: IO[Any], file_name: str) -> str:
    from unstructured.staging.base import dict_to_elements
    from unstructured_client import UnstructuredClient

    logger.debug("Starting to read file: %s", file_name)
    req = _sdk_partition_request(file, file_name, strategy="fast")

    unstructured_client = UnstructuredClient(api_key_auth=get_unstructured_api_key())

    response = unstructured_client.general.partition(request=req)

    if response.status_code != 200:
        err = f"Received unexpected status code {response.status_code} from Unstructured API."
        logger.error(err)
        raise ValueError(err)

    elements = dict_to_elements(response.elements or [])
    return "\n\n".join(str(el) for el in elements)
