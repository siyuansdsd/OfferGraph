"""Synthesize reusable Playwright tool recipes from browser memory traces."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.memory.models import MemoryRecord
from agent.memory.store import get_default_memory_store, memory_enabled


class PlaywrightToolSynthesizerInput(BaseModel):
    """Input schema for synthesizing a Playwright flow recipe."""

    query: str = Field(
        default="",
        description="Optional text query to match prior browser traces.",
    )
    module: str = Field(
        default="linkedin_jobs",
        description="Memory module to search, for example linkedin_jobs.",
    )
    tags: list[str] = Field(
        default_factory=lambda: ["linkedin-jobs-explorer"],
        description="Trace tags that must be present.",
    )
    limit: int = Field(default=10, ge=1, le=50, description="Maximum traces to inspect.")


@tool("playwright-tool-synthesizer", args_schema=PlaywrightToolSynthesizerInput)
def playwright_tool_synthesizer(
    query: str = "",
    module: str = "linkedin_jobs",
    tags: list[str] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Summarize prior Playwright traces into a reusable tool recipe."""
    if not memory_enabled():
        return {
            "status": "disabled",
            "message": "OfferGraph memory is disabled.",
            "recipe": None,
        }

    records = get_default_memory_store().search(
        query=query,
        module=module,
        kind="browser_trace",
        tags=tags or ["linkedin-jobs-explorer"],
        limit=limit,
    )
    recipe = synthesize_playwright_recipe(records)
    return {
        "status": "ok",
        "trace_count": len(records),
        "source_record_ids": [record.id for record in records],
        "recipe": recipe,
    }


def synthesize_playwright_recipe(records: list[MemoryRecord]) -> dict[str, Any]:
    """Build a deterministic recipe summary from browser trace records."""
    selector_stats: dict[str, Counter[str]] = defaultdict(Counter)
    label_stats: Counter[str] = Counter()
    url_stats: Counter[str] = Counter()
    extracted_keys: Counter[str] = Counter()
    statuses: Counter[str] = Counter()

    for record in records:
        statuses["success" if record.success else "failure"] += 1
        if record.source_url:
            url_stats[record.source_url] += 1
        payload = record.payload or {}
        for action in payload.get("actions", []):
            label = str(action.get("label") or "")
            action_type = str(action.get("type") or "unknown")
            selector = action.get("selector")
            if label:
                label_stats[label] += 1
            if selector:
                bucket = "success" if action.get("success", True) else "failure"
                selector_stats[str(selector)][bucket] += 1
                selector_stats[str(selector)][f"type:{action_type}"] += 1
        extracted_data = payload.get("extracted_data") or {}
        for key in extracted_data:
            extracted_keys[str(key)] += 1

    stable_selectors = [
        {
            "selector": selector,
            "success_count": counts["success"],
            "failure_count": counts["failure"],
            "action_types": sorted(
                key.removeprefix("type:")
                for key in counts
                if key.startswith("type:")
            ),
        }
        for selector, counts in selector_stats.items()
        if counts["success"] > 0
    ]
    stable_selectors.sort(
        key=lambda item: (item["success_count"], -item["failure_count"]),
        reverse=True,
    )

    return {
        "success_count": statuses["success"],
        "failure_count": statuses["failure"],
        "common_urls": [
            {"url": url, "count": count} for url, count in url_stats.most_common(5)
        ],
        "common_steps": [
            {"label": label, "count": count}
            for label, count in label_stats.most_common(12)
        ],
        "stable_selectors": stable_selectors[:20],
        "common_extracted_data": [
            {"key": key, "count": count}
            for key, count in extracted_keys.most_common(12)
        ],
        "recommended_flow": [
            "Start from tools.playwright_template.PlaywrightToolSpec.",
            "Implement only a small flow(page, trace) function for the target workflow.",
            "Use navigate(), click_first_visible(), set_first_file_input(), and trace.action().",
            "Persist extracted data through trace.add_extracted_data() or returned extracted_data.",
            "Stop before irreversible actions unless a terminal y/n confirmation succeeds.",
            "Add unit tests with fake Playwright page/context objects before enabling broad use.",
        ],
    }


__all__ = [
    "PlaywrightToolSynthesizerInput",
    "playwright_tool_synthesizer",
    "synthesize_playwright_recipe",
]
