"""Browser automation memory helpers."""

from __future__ import annotations

from typing import Any

from agent.memory.models import BrowserAction, BrowserTrace, MemoryRecord
from agent.memory.store import SQLiteMemoryStore, get_default_memory_store, memory_enabled


def build_browser_trace_record(
    trace: BrowserTrace,
    *,
    module: str = "browser",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> MemoryRecord:
    """Build a memory record from a browser automation trace."""
    active_tags = _dedupe_tags(["browser", "playwright", *(tags or [])])
    return MemoryRecord(
        module=module,
        kind="browser_trace",
        task=trace.task,
        summary=summarize_browser_trace(trace),
        source_url=trace.url,
        success=trace.success,
        tags=active_tags,
        payload=trace.model_dump(mode="json"),
        metadata=metadata or {},
    )


def record_browser_trace(
    *,
    task: str,
    final_result: str,
    success: bool,
    url: str | None = None,
    actions: list[BrowserAction | dict[str, Any]] | None = None,
    screenshots: list[str] | None = None,
    dom_snapshot: str | None = None,
    extracted_data: dict[str, Any] | None = None,
    error: str | None = None,
    module: str = "browser",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    store: SQLiteMemoryStore | None = None,
) -> MemoryRecord | None:
    """Persist a browser trace when memory is enabled."""
    if not memory_enabled():
        return None

    trace = BrowserTrace(
        task=task,
        final_result=final_result,
        success=success,
        url=url,
        actions=[
            action if isinstance(action, BrowserAction) else BrowserAction(**action)
            for action in (actions or [])
        ],
        screenshots=screenshots or [],
        dom_snapshot=dom_snapshot,
        extracted_data=extracted_data or {},
        error=error,
    )
    record = build_browser_trace_record(
        trace,
        module=module,
        tags=tags,
        metadata=metadata,
    )
    active_store = store or get_default_memory_store()
    return active_store.append(record)


def record_browser_trace_safely(**kwargs: Any) -> MemoryRecord | None:
    """Persist a browser trace without letting memory failures break the tool."""
    try:
        return record_browser_trace(**kwargs)
    except Exception:
        return None


def summarize_browser_trace(trace: BrowserTrace) -> str:
    """Build a compact summary for browser trace retrieval."""
    status = "succeeded" if trace.success else "failed"
    action_count = len(trace.actions)
    target = trace.url or "browser"
    task = " ".join(trace.task.split())[:160] or "untitled task"
    result = " ".join(trace.final_result.split())[:160]
    return (
        f"Browser trace {status} for '{task}' at {target}. "
        f"Actions: {action_count}. Final result: {result}"
    )


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for tag in tags:
        normalized = tag.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped
