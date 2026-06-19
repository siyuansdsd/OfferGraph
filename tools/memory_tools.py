"""Agent memory tools."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent.memory import record_browser_trace
from agent.memory.models import MemoryRecord
from agent.memory.store import get_default_memory_store, memory_enabled


class MemorySearchInput(BaseModel):
    """Input schema for memory-search."""

    query: str = Field(
        default="",
        description="Text to search in prior memory records.",
    )
    module: str | None = Field(
        default=None,
        description="Optional module filter, for example browser, linkedin, github.",
    )
    kind: str | None = Field(
        default=None,
        description="Optional record kind filter, for example browser_trace.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Optional tags that must appear in matched records.",
    )
    limit: int = Field(
        default=5,
        description="Maximum records to return.",
    )
    include_payload: bool = Field(
        default=False,
        description="Whether to include full stored payloads in results.",
    )


class MemoryBrowserTraceInput(BaseModel):
    """Input schema for memory-record-browser-trace."""

    task: str = Field(..., description="Browser task that was executed.")
    final_result: str = Field(..., description="Final result or status from the task.")
    success: bool = Field(..., description="Whether the task succeeded.")
    url: str | None = Field(default=None, description="Final or primary page URL.")
    actions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Browser actions with type, label, url, selector, success, details.",
    )
    extracted_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured extracted data from the browser task.",
    )
    error: str | None = Field(default=None, description="Failure detail if any.")
    module: str = Field(
        default="browser",
        description="Module namespace for this memory record.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for future retrieval.",
    )


@tool("memory-search", args_schema=MemorySearchInput)
def memory_search(
    query: str = "",
    module: str | None = None,
    kind: str | None = None,
    tags: list[str] | None = None,
    limit: int = 5,
    include_payload: bool = False,
) -> dict[str, Any]:
    """Search OfferGraph persistent memory before repeating previous work."""
    if not memory_enabled():
        return {
            "status": "disabled",
            "message": "OfferGraph memory is disabled.",
            "records": [],
        }

    records = get_default_memory_store().search(
        query=query,
        module=module,
        kind=kind,
        tags=tags or [],
        limit=limit,
    )
    return {
        "status": "ok",
        "count": len(records),
        "records": [
            _serialize_record(record, include_payload=include_payload)
            for record in records
        ],
    }


@tool("memory-record-browser-trace", args_schema=MemoryBrowserTraceInput)
def memory_record_browser_trace(
    task: str,
    final_result: str,
    success: bool,
    url: str | None = None,
    actions: list[dict[str, Any]] | None = None,
    extracted_data: dict[str, Any] | None = None,
    error: str | None = None,
    module: str = "browser",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Record a browser automation trace for future agent retrieval."""
    record = record_browser_trace(
        task=task,
        final_result=final_result,
        success=success,
        url=url,
        actions=actions or [],
        extracted_data=extracted_data or {},
        error=error,
        module=module,
        tags=tags or [],
    )
    if record is None:
        return {
            "status": "disabled",
            "message": "OfferGraph memory is disabled.",
        }
    return {
        "status": "recorded",
        "id": record.id,
        "summary": record.summary,
    }


def _serialize_record(
    record: MemoryRecord,
    *,
    include_payload: bool = False,
) -> dict[str, Any]:
    data = {
        "id": record.id,
        "created_at": record.created_at.isoformat(),
        "module": record.module,
        "kind": record.kind,
        "task": record.task,
        "summary": record.summary,
        "source_url": record.source_url,
        "success": record.success,
        "tags": record.tags,
    }
    if include_payload:
        data["payload"] = record.payload
        data["metadata"] = record.metadata
    return data
