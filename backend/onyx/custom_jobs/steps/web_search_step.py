from __future__ import annotations

import time
from typing import Any

from onyx.custom_jobs.types import BaseStep
from onyx.custom_jobs.types import StepContext
from onyx.custom_jobs.types import StepResult
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from shared_configs.enums import WebSearchProviderType


class WebSearchStep(BaseStep):
    step_key = "web_search"
    _cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def _evict_cache(self, *, now: float, max_entries: int) -> None:
        expired_keys = [
            query for query, (expires_at, _) in self._cache.items() if expires_at <= now
        ]
        for query in expired_keys:
            self._cache.pop(query, None)

        if max_entries < 1:
            return

        overflow = len(self._cache) - max_entries
        if overflow <= 0:
            return

        for query in list(self._cache.keys())[:overflow]:
            self._cache.pop(query, None)

    def run(self, context: StepContext) -> StepResult:
        provider_model = fetch_active_web_search_provider(context.db_session)
        if provider_model is None:
            return StepResult.failure("No active web search provider configured.")

        provider_type = WebSearchProviderType(provider_model.provider_type)
        api_key = (
            provider_model.api_key.get_value(apply_mask=False)
            if provider_model.api_key is not None
            else None
        )
        provider = build_search_provider_from_config(
            provider_type=provider_type,
            api_key=api_key,
            config=provider_model.config or {},
        )

        ttl_seconds = int(context.step_config.get("cache_ttl_seconds", 300))
        max_cache_entries = int(context.step_config.get("max_cache_entries", 256))
        max_results = int(context.step_config.get("max_results", 5))
        queries = context.step_config.get("queries") or []
        if not queries:
            return StepResult.skipped(
                output_json={"results": [], "errors": [], "query_count": 0},
                reason="No web search queries provided.",
            )

        all_results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        now = time.time()
        self._evict_cache(now=now, max_entries=max_cache_entries)

        for query in queries:
            cached = self._cache.get(query)
            if cached and cached[0] > now:
                # Maintain rough LRU order for bounded cache eviction.
                self._cache.pop(query, None)
                self._cache[query] = cached
                all_results.extend(cached[1])
                continue

            try:
                query_results = list(provider.search(query))[:max_results]
                serialized = [
                    {
                        "query": query,
                        "title": item.title,
                        "url": item.link,
                        "snippet": item.snippet,
                    }
                    for item in query_results
                ]
                all_results.extend(serialized)
                self._cache[query] = (now + ttl_seconds, serialized)
                self._evict_cache(now=now, max_entries=max_cache_entries)
            except Exception as e:
                errors.append({"query": query, "error": str(e)})

        if not all_results and errors:
            return StepResult.failure(
                f"Web search failed for all queries. errors={errors}"
            )

        return StepResult.success(
            output_json={
                "results": all_results,
                "errors": errors,
                "query_count": len(queries),
                "provider_type": provider_type.value,
            }
        )
