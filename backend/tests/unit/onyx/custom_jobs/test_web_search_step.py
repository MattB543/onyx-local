from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.custom_jobs.steps.web_search_step import WebSearchStep
from onyx.custom_jobs.types import StepContext
from onyx.db.enums import CustomJobStepStatus


def _context(step_config: dict) -> StepContext:
    return StepContext(
        db_session=MagicMock(),
        tenant_id="public",
        run_id=uuid4(),
        job_id=uuid4(),
        job_config={},
        step_config=step_config,
        previous_outputs={},
        deadline_monotonic=1_000_000.0,
    )


def _provider_model() -> SimpleNamespace:
    return SimpleNamespace(
        provider_type="serper",
        api_key=SimpleNamespace(get_value=lambda apply_mask=False: "api-key"),  # noqa: ARG005
        config={},
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    WebSearchStep._cache.clear()


# ------------------------------------------------------------------
# Existing tests
# ------------------------------------------------------------------


def test_web_search_step_fails_without_active_provider() -> None:
    step = WebSearchStep()
    context = _context({"queries": ["query one"]})

    with patch(
        "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
        return_value=None,
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.FAILURE
    assert "No active web search provider configured" in str(result.error_message)


def test_web_search_step_skips_without_queries() -> None:
    step = WebSearchStep()
    context = _context({"queries": []})

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config"
        ) as mock_build_provider,
    ):
        mock_build_provider.return_value = MagicMock()
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SKIPPED
    assert result.output_json == {"results": [], "errors": [], "query_count": 0}


def test_web_search_step_uses_cache_on_repeat_query() -> None:
    """Verify cached data is reused and appears correctly in output."""
    step = WebSearchStep()
    context = _context({"queries": ["onyx"], "cache_ttl_seconds": 300, "max_results": 5})

    provider = MagicMock()
    provider.search.return_value = [
        SimpleNamespace(title="A", link="https://a.example", snippet="alpha")
    ]

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
    ):
        first = step.run(context)
        second = step.run(context)

    assert first.status == CustomJobStepStatus.SUCCESS
    assert second.status == CustomJobStepStatus.SUCCESS
    assert provider.search.call_count == 1

    # Fix #4: verify cached data appears correctly in the second run's output
    expected_result = {
        "query": "onyx",
        "title": "A",
        "url": "https://a.example",
        "snippet": "alpha",
    }
    assert first.output_json is not None
    assert second.output_json is not None
    assert expected_result in first.output_json["results"]
    assert expected_result in second.output_json["results"]


def test_web_search_step_bounds_cache_size() -> None:
    """Cache should be bounded; only the most recent entry should survive."""
    step = WebSearchStep()
    context = _context(
        {
            "queries": ["q1", "q2"],
            "cache_ttl_seconds": 300,
            "max_results": 1,
            "max_cache_entries": 1,
        }
    )

    provider = MagicMock()
    provider.search.side_effect = [
        [SimpleNamespace(title="T1", link="https://1", snippet="S1")],
        [SimpleNamespace(title="T2", link="https://2", snippet="S2")],
    ]

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    # Fix #5: strengthen from <= 1 to == 1
    assert len(WebSearchStep._cache) == 1
    # Fix #5: verify the most recent entry ("q2") survives eviction
    assert "q2" in WebSearchStep._cache
    assert "q1" not in WebSearchStep._cache


def test_web_search_step_fails_when_all_queries_error() -> None:
    step = WebSearchStep()
    context = _context({"queries": ["q1", "q2"]})

    provider = MagicMock()
    provider.search.side_effect = RuntimeError("search backend down")

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.FAILURE
    assert "Web search failed for all queries" in str(result.error_message)


# ------------------------------------------------------------------
# New tests
# ------------------------------------------------------------------


def test_web_search_step_partial_failure_continues_with_successful_results() -> None:
    """Requirement 6.3.3: partial failures should still return SUCCESS.

    Query 1 succeeds, query 2 raises, query 3 succeeds.
    The step should return SUCCESS with results from queries 1 and 3,
    and the errors list should contain query 2's error.
    """
    step = WebSearchStep()
    context = _context({"queries": ["good1", "bad", "good2"], "max_results": 5})

    provider = MagicMock()
    provider.search.side_effect = [
        [SimpleNamespace(title="R1", link="https://r1.example", snippet="result one")],
        RuntimeError("provider timeout"),
        [SimpleNamespace(title="R3", link="https://r3.example", snippet="result three")],
    ]

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS

    assert result.output_json is not None
    results = result.output_json["results"]
    errors = result.output_json["errors"]

    # Results from queries 1 and 3 are present
    result_queries = [r["query"] for r in results]
    assert "good1" in result_queries
    assert "good2" in result_queries
    assert len(results) == 2

    # Errors list contains query 2's error
    assert len(errors) == 1
    assert errors[0]["query"] == "bad"
    assert "provider timeout" in errors[0]["error"]


def test_web_search_step_cache_ttl_expiry() -> None:
    """Cached results should be invalidated after the TTL expires."""
    step = WebSearchStep()
    context = _context({"queries": ["onyx"], "cache_ttl_seconds": 60, "max_results": 5})

    provider = MagicMock()
    provider.search.side_effect = [
        [SimpleNamespace(title="Old", link="https://old.example", snippet="stale")],
        [SimpleNamespace(title="New", link="https://new.example", snippet="fresh")],
    ]

    base_time = 1_000_000.0

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
        patch("onyx.custom_jobs.steps.web_search_step.time") as mock_time,
    ):
        # First call: time is at base_time
        mock_time.time.return_value = base_time
        first = step.run(context)

        # Second call: time has advanced past the 60s TTL
        mock_time.time.return_value = base_time + 61
        second = step.run(context)

    assert first.status == CustomJobStepStatus.SUCCESS
    assert second.status == CustomJobStepStatus.SUCCESS

    # Provider should have been called twice (cache was invalidated)
    assert provider.search.call_count == 2

    # Second result should contain the fresh data
    assert second.output_json is not None
    assert second.output_json["results"][0]["title"] == "New"
    assert second.output_json["results"][0]["snippet"] == "fresh"


def test_web_search_step_success_output_structure() -> None:
    """Verify the full output structure after a successful run."""
    step = WebSearchStep()
    context = _context({"queries": ["alpha", "beta"], "max_results": 5})

    provider = MagicMock()
    provider.search.side_effect = [
        [
            SimpleNamespace(title="A1", link="https://a1.example", snippet="snap a1"),
            SimpleNamespace(title="A2", link="https://a2.example", snippet="snap a2"),
        ],
        [
            SimpleNamespace(title="B1", link="https://b1.example", snippet="snap b1"),
        ],
    ]

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None

    # Check all required top-level keys exist
    assert set(result.output_json.keys()) == {
        "results",
        "errors",
        "query_count",
        "provider_type",
    }

    # Check values
    assert result.output_json["query_count"] == 2
    assert result.output_json["provider_type"] == "serper"
    assert result.output_json["errors"] == []
    assert len(result.output_json["results"]) == 3

    # Verify individual result structure
    for item in result.output_json["results"]:
        assert set(item.keys()) == {"query", "title", "url", "snippet"}


def test_web_search_step_max_results_truncation() -> None:
    """Results should be truncated to max_results per query."""
    step = WebSearchStep()
    context = _context({"queries": ["big"], "max_results": 2})

    provider = MagicMock()
    provider.search.return_value = [
        SimpleNamespace(title="R1", link="https://1", snippet="S1"),
        SimpleNamespace(title="R2", link="https://2", snippet="S2"),
        SimpleNamespace(title="R3", link="https://3", snippet="S3"),
        SimpleNamespace(title="R4", link="https://4", snippet="S4"),
    ]

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    assert len(result.output_json["results"]) == 2
    # Should keep the first max_results items
    assert result.output_json["results"][0]["title"] == "R1"
    assert result.output_json["results"][1]["title"] == "R2"


def test_web_search_step_missing_queries_key() -> None:
    """Graceful handling when 'queries' key is missing from step_config."""
    step = WebSearchStep()
    context = _context({})  # No "queries" key at all

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config"
        ) as mock_build_provider,
    ):
        mock_build_provider.return_value = MagicMock()
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SKIPPED
    assert result.output_json == {"results": [], "errors": [], "query_count": 0}


def test_web_search_step_default_config_values() -> None:
    """Defaults are applied when optional config keys are omitted.

    Specifically, the step should use its defaults for cache_ttl_seconds,
    max_cache_entries, and max_results when those keys are absent.
    """
    step = WebSearchStep()
    # Only provide queries; everything else should use defaults
    context = _context({"queries": ["default_test"]})

    provider = MagicMock()
    provider.search.return_value = [
        SimpleNamespace(title=f"T{i}", link=f"https://{i}", snippet=f"S{i}")
        for i in range(10)
    ]

    with (
        patch(
            "onyx.custom_jobs.steps.web_search_step.fetch_active_web_search_provider",
            return_value=_provider_model(),
        ),
        patch(
            "onyx.custom_jobs.steps.web_search_step.build_search_provider_from_config",
            return_value=provider,
        ),
    ):
        result = step.run(context)

    assert result.status == CustomJobStepStatus.SUCCESS
    assert result.output_json is not None
    # Default max_results is 5, so only 5 results should appear
    assert len(result.output_json["results"]) == 5
