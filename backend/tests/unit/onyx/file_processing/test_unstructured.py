from unittest.mock import MagicMock

from onyx.file_processing.unstructured import update_unstructured_api_key
from onyx.configs.constants import KV_UNSTRUCTURED_API_KEY


def test_update_unstructured_api_key_uses_encrypted_kv_store(
    monkeypatch,
) -> None:
    kv_store = MagicMock()
    monkeypatch.setattr(
        "onyx.file_processing.unstructured.get_kv_store",
        lambda: kv_store,
    )

    update_unstructured_api_key("test-api-key")

    kv_store.store.assert_called_once_with(
        KV_UNSTRUCTURED_API_KEY,
        "test-api-key",
        encrypt=True,
    )
