from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import onyx.tools.tool_implementations.web_search.clients.exa_client as exa_module
import onyx.tools.tool_implementations.web_search.clients.google_pse_client as google_module
import onyx.tools.tool_implementations.web_search.clients.searxng_client as searxng_module
import onyx.tools.tool_implementations.web_search.clients.serper_client as serper_module
from onyx.tools.tool_implementations.web_search.clients.exa_client import ExaClient
from onyx.tools.tool_implementations.web_search.clients.google_pse_client import (
    GooglePSEClient,
)
from onyx.tools.tool_implementations.web_search.clients.searxng_client import (
    SearXNGClient,
)
from onyx.tools.tool_implementations.web_search.clients.serper_client import (
    SerperClient,
)


class DummyResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_serper_search_maps_image_url(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SerperClient(api_key="test-key")

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            {
                "organic": [
                    {
                        "title": "Result",
                        "link": "https://example.com/article",
                        "snippet": "Snippet",
                        "imageUrl": " https://example.com/image.jpg ",
                    }
                ]
            }
        )

    monkeypatch.setattr(serper_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].image == "https://example.com/image.jpg"


def test_searxng_search_maps_image_url(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SearXNGClient(searxng_base_url="https://searx.example.com")

    def _mock_post(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            {
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.com/article",
                        "content": "Snippet",
                        "img_src": " https://example.com/image.jpg ",
                    }
                ]
            }
        )

    monkeypatch.setattr(searxng_module.requests, "post", _mock_post)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].image == "https://example.com/image.jpg"


def test_google_pse_search_maps_image_url(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GooglePSEClient(api_key="test-key", search_engine_id="test-cx")

    def _mock_get(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            {
                "items": [
                    {
                        "title": "Result",
                        "link": "https://example.com/article",
                        "snippet": "Snippet",
                        "pagemap": {
                            "cse_image": [{"src": " https://example.com/image.jpg "}],
                            "metatags": [{"og:image": "https://example.com/fallback.jpg"}],
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(google_module.requests, "get", _mock_get)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].image == "https://example.com/image.jpg"


def test_google_pse_search_falls_back_to_og_image(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GooglePSEClient(api_key="test-key", search_engine_id="test-cx")

    def _mock_get(*args: Any, **kwargs: Any) -> DummyResponse:  # noqa: ARG001
        return DummyResponse(
            {
                "items": [
                    {
                        "title": "Result",
                        "link": "https://example.com/article",
                        "snippet": "Snippet",
                        "pagemap": {
                            "metatags": [{"og:image": " https://example.com/image.jpg "}],
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(google_module.requests, "get", _mock_get)

    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].image == "https://example.com/image.jpg"


def test_exa_search_maps_image_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyExaWithTimeout:
        def __init__(self, api_key: str) -> None:  # noqa: ARG002
            pass

        def search_and_contents(self, *args: Any, **kwargs: Any) -> SimpleNamespace:  # noqa: ARG002
            return SimpleNamespace(
                results=[
                    SimpleNamespace(
                        title="Result",
                        url="https://example.com/article",
                        highlights=["Snippet"],
                        author=None,
                        published_date=None,
                        image=" https://example.com/image.jpg ",
                    )
                ]
            )

    monkeypatch.setattr(exa_module, "ExaWithTimeout", DummyExaWithTimeout)

    client = ExaClient(api_key="test-key")
    results = client.search("onyx")

    assert len(results) == 1
    assert results[0].image == "https://example.com/image.jpg"
