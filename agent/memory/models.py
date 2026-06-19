"""Shared memory data models."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class MemoryRecord(BaseModel):
    """Durable memory record that can be reused by agents and tools."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    module: str
    kind: str
    task: str = ""
    summary: str
    source_url: str | None = None
    success: bool | None = None
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrowserAction(BaseModel):
    """A single browser automation step."""

    type: str
    label: str
    url: str | None = None
    selector: str | None = None
    success: bool = True
    details: dict[str, Any] = Field(default_factory=dict)


class BrowserTrace(BaseModel):
    """Trace from a Playwright/browser automation run."""

    task: str
    final_result: str
    success: bool
    url: str | None = None
    actions: list[BrowserAction] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    dom_snapshot: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
