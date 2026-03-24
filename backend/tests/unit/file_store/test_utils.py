from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import FileOrigin
from onyx.file_store.utils import save_file_from_url


def _make_response(
    *,
    headers: dict[str, str] | None = None,
    chunks: list[bytes] | None = None,
) -> MagicMock:
    response = MagicMock()
    response.headers = headers or {}
    response.iter_content.return_value = chunks or [b"abc", b"123"]
    response.raise_for_status.return_value = None
    return response


def test_save_file_from_url_downloads_via_ssrf_safe_get_and_persists_content() -> None:
    response = _make_response(headers={"Content-Type": "image/png; charset=utf-8"})
    file_store = MagicMock()
    file_store.save_file.return_value = "file-123"

    with (
        patch("onyx.file_store.utils.ssrf_safe_get", return_value=response) as mock_get,
        patch("onyx.file_store.utils.get_default_file_store", return_value=file_store),
    ):
        file_id = save_file_from_url(
            "https://example.com/avatar.png",
            display_name="avatar.png",
            file_origin=FileOrigin.CRM_UPLOAD,
            timeout=(1, 2),
            max_bytes=32,
            require_image=True,
        )

    assert file_id == "file-123"
    mock_get.assert_called_once_with(
        "https://example.com/avatar.png",
        timeout=(1, 2),
        stream=True,
    )
    save_kwargs = file_store.save_file.call_args.kwargs
    assert save_kwargs["display_name"] == "avatar.png"
    assert save_kwargs["file_origin"] == FileOrigin.CRM_UPLOAD
    assert save_kwargs["file_type"] == "image/png"
    assert save_kwargs["content"].read() == b"abc123"
    response.close.assert_called_once()


def test_save_file_from_url_require_image_rejects_missing_content_type() -> None:
    response = _make_response(headers={})

    with patch("onyx.file_store.utils.ssrf_safe_get", return_value=response):
        with pytest.raises(ValueError, match="Content-Type header"):
            save_file_from_url(
                "https://example.com/avatar",
                require_image=True,
            )

    response.close.assert_called_once()


def test_save_file_from_url_require_image_rejects_non_image_response() -> None:
    response = _make_response(headers={"Content-Type": "text/html"})

    with patch("onyx.file_store.utils.ssrf_safe_get", return_value=response):
        with pytest.raises(ValueError, match="did not return an image Content-Type"):
            save_file_from_url(
                "https://example.com/avatar",
                require_image=True,
            )

    response.close.assert_called_once()


def test_save_file_from_url_enforces_max_bytes_before_saving() -> None:
    response = _make_response(
        headers={"Content-Type": "image/png"},
        chunks=[b"abcd", b"ef"],
    )
    file_store = MagicMock()

    with (
        patch("onyx.file_store.utils.ssrf_safe_get", return_value=response),
        patch("onyx.file_store.utils.get_default_file_store", return_value=file_store),
    ):
        with pytest.raises(ValueError, match="maximum allowed size"):
            save_file_from_url(
                "https://example.com/avatar.png",
                max_bytes=5,
            )

    file_store.save_file.assert_not_called()
    response.close.assert_called_once()
