"""Reusable template primitives for Playwright-backed LangChain tools."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from agent.memory import record_browser_trace_safely
from agent.memory.models import BrowserAction, MemoryRecord
from config.env import PROJECT_ROOT


DEFAULT_PLAYWRIGHT_TOOL_TIMEOUT_MS = 15_000
DEFAULT_SCREENSHOT_DIR = PROJECT_ROOT / "local_data" / "memory" / "screenshots"
PlaywrightFlow = Callable[[Any, "PlaywrightToolTrace"], dict[str, Any]]


@dataclass(frozen=True)
class PlaywrightToolSpec:
    """Configuration shared by Playwright-backed tools."""

    tool_name: str
    task: str
    start_url: str
    module: str
    tags: list[str] = field(default_factory=list)
    session_state_path: str | None = None
    headless: bool = False
    capture_screenshot: bool = False
    capture_dom_snapshot: bool = False
    screenshot_dir: str | Path = DEFAULT_SCREENSHOT_DIR
    timeout_ms: int = DEFAULT_PLAYWRIGHT_TOOL_TIMEOUT_MS


class PlaywrightToolTrace:
    """Collect browser actions and persist them as OfferGraph memory."""

    def __init__(self, spec: PlaywrightToolSpec) -> None:
        self.spec = spec
        self.actions: list[BrowserAction] = []
        self.screenshots: list[str] = []
        self.dom_snapshot: str | None = None
        self.extracted_data: dict[str, Any] = {}

    def action(
        self,
        action_type: str,
        label: str,
        *,
        url: str | None = None,
        selector: str | None = None,
        success: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append one browser action to the trace."""
        self.actions.append(
            BrowserAction(
                type=action_type,
                label=label,
                url=url,
                selector=selector,
                success=success,
                details=details or {},
            )
        )

    def add_extracted_data(self, key: str, value: Any) -> None:
        """Attach structured data collected by the tool flow."""
        self.extracted_data[key] = value

    def capture_screenshot(self, page: Any, label: str) -> str | None:
        """Save a local screenshot path for the trace when Playwright supports it."""
        path = _build_screenshot_path(self.spec.screenshot_dir, self.spec.tool_name, label)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(path), full_page=True)
            self.screenshots.append(str(path))
            self.action(
                "screenshot",
                f"Captured screenshot: {label}",
                url=getattr(page, "url", None),
                success=True,
                details={"path": str(path)},
            )
            return str(path)
        except Exception as exc:
            self.action(
                "screenshot",
                f"Failed to capture screenshot: {label}",
                url=getattr(page, "url", None),
                success=False,
                details={"error": str(exc)},
            )
            return None

    def capture_dom_snapshot(self, page: Any, *, max_chars: int = 5_000) -> str | None:
        """Capture a compact DOM snapshot for later tool synthesis."""
        try:
            content = page.content()
        except Exception as exc:
            self.action(
                "dom_snapshot",
                "Failed to capture DOM snapshot",
                url=getattr(page, "url", None),
                success=False,
                details={"error": str(exc)},
            )
            return None

        self.dom_snapshot = " ".join(content.split())[:max_chars]
        self.action(
            "dom_snapshot",
            "Captured DOM snapshot",
            url=getattr(page, "url", None),
            success=True,
            details={"characters": len(self.dom_snapshot)},
        )
        return self.dom_snapshot

    def persist(
        self,
        *,
        final_result: str,
        success: bool,
        url: str | None = None,
        error: str | None = None,
        module: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRecord | None:
        """Persist the collected trace in OfferGraph memory."""
        active_metadata = {
            "tool_name": self.spec.tool_name,
            "start_url": self.spec.start_url,
        }
        active_metadata.update(metadata or {})
        return record_browser_trace_safely(
            task=self.spec.task,
            final_result=final_result,
            success=success,
            url=url or self.spec.start_url,
            actions=self.actions,
            screenshots=self.screenshots,
            dom_snapshot=self.dom_snapshot,
            extracted_data=self.extracted_data,
            error=error,
            module=module or self.spec.module,
            tags=tags or [self.spec.tool_name, *self.spec.tags],
            metadata=active_metadata,
        )


def run_playwright_flow(
    spec: PlaywrightToolSpec,
    flow: PlaywrightFlow,
    *,
    playwright_factory: Callable[[], Any] = sync_playwright,
) -> dict[str, Any]:
    """Run a browser flow and record a reusable trace."""
    trace = PlaywrightToolTrace(spec)
    browser = None
    page = None
    try:
        with playwright_factory() as playwright:
            browser = playwright.chromium.launch(headless=spec.headless)
            context_kwargs = {}
            if spec.session_state_path:
                context_kwargs["storage_state"] = str(
                    Path(spec.session_state_path).expanduser().resolve()
                )
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            result = flow(page, trace)
            if spec.capture_screenshot:
                trace.capture_screenshot(page, "final")
            if spec.capture_dom_snapshot:
                trace.capture_dom_snapshot(page)

            final_result = str(result.get("message") or result.get("status") or "done")
            success = bool(result.get("success", result.get("status") != "error"))
            if result.get("extracted_data"):
                trace.extracted_data.update(result["extracted_data"])
            record = trace.persist(
                final_result=final_result,
                success=success,
                url=result.get("memory_url") or getattr(page, "url", spec.start_url),
                error=result.get("error"),
                module=result.get("memory_module"),
                tags=result.get("memory_tags"),
                metadata=result.get("memory_metadata"),
            )
            result["memory_record_id"] = record.id if record else None
            result["trace_actions"] = [action.model_dump(mode="json") for action in trace.actions]
            result["screenshots"] = trace.screenshots
            return result
    except Exception as exc:
        trace.action(
            "error",
            "Playwright flow failed",
            url=getattr(page, "url", spec.start_url) if page else spec.start_url,
            success=False,
            details={"error": str(exc)},
        )
        record = trace.persist(
            final_result=f"Playwright flow failed: {exc}",
            success=False,
            url=getattr(page, "url", spec.start_url) if page else spec.start_url,
            error=str(exc),
        )
        return {
            "status": "error",
            "success": False,
            "message": str(exc),
            "memory_record_id": record.id if record else None,
            "trace_actions": [action.model_dump(mode="json") for action in trace.actions],
            "screenshots": trace.screenshots,
        }
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def navigate(
    page: Any,
    trace: PlaywrightToolTrace,
    url: str,
    *,
    wait_until: str = "domcontentloaded",
    timeout: int | None = None,
) -> None:
    """Navigate and record the action."""
    page.goto(
        url,
        wait_until=wait_until,
        timeout=timeout or trace.spec.timeout_ms,
    )
    trace.action("navigate", f"Open {url}", url=getattr(page, "url", url), success=True)


def wait_for_load_state(
    page: Any,
    trace: PlaywrightToolTrace,
    state: str = "networkidle",
    *,
    timeout: int | None = None,
) -> bool:
    """Wait for a load state without failing the whole tool."""
    try:
        page.wait_for_load_state(state, timeout=timeout or trace.spec.timeout_ms)
        trace.action(
            "wait",
            f"Waited for load state: {state}",
            url=getattr(page, "url", None),
            success=True,
        )
        return True
    except PlaywrightError as exc:
        trace.action(
            "wait",
            f"Load state not reached: {state}",
            url=getattr(page, "url", None),
            success=False,
            details={"error": str(exc)},
        )
        return False


def first_visible_locator(
    page: Any,
    selectors: tuple[str, ...],
    *,
    timeout: int = 2_000,
) -> tuple[str, Any] | tuple[None, None]:
    """Return the first visible locator from a selector list."""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="visible", timeout=timeout)
            return selector, locator
        except PlaywrightError:
            continue
    return None, None


def first_attached_locator(
    page: Any,
    selectors: tuple[str, ...],
    *,
    timeout: int = 2_000,
) -> tuple[str, Any] | tuple[None, None]:
    """Return the first attached locator from a selector list."""
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="attached", timeout=timeout)
            return selector, locator
        except PlaywrightError:
            continue
    return None, None


def click_first_visible(
    page: Any,
    trace: PlaywrightToolTrace,
    selectors: tuple[str, ...],
    *,
    label: str,
    timeout: int = 2_000,
) -> tuple[str | None, bool]:
    """Click the first visible selector and record success/failure."""
    selector, locator = first_visible_locator(page, selectors, timeout=timeout)
    if not selector or locator is None:
        trace.action(
            "click",
            label,
            url=getattr(page, "url", None),
            selector=None,
            success=False,
            details={"reason": "no visible selector matched", "selectors": selectors},
        )
        return None, False

    locator.click()
    trace.action(
        "click",
        label,
        url=getattr(page, "url", None),
        selector=selector,
        success=True,
    )
    return selector, True


def set_first_file_input(
    page: Any,
    trace: PlaywrightToolTrace,
    selectors: tuple[str, ...],
    file_path: str | Path,
    *,
    label: str,
    timeout: int = 2_000,
) -> tuple[str | None, bool]:
    """Set a file input and record the action."""
    selector, locator = first_attached_locator(page, selectors, timeout=timeout)
    resolved_path = Path(file_path).expanduser().resolve()
    if not selector or locator is None:
        trace.action(
            "upload_file",
            label,
            url=getattr(page, "url", None),
            success=False,
            details={"reason": "no attached file input matched", "path": str(resolved_path)},
        )
        return None, False

    locator.set_input_files(str(resolved_path))
    trace.action(
        "upload_file",
        label,
        url=getattr(page, "url", None),
        selector=selector,
        success=True,
        details={"path": str(resolved_path)},
    )
    return selector, True


def compact_text(value: str, *, max_chars: int = 500) -> str:
    """Normalize whitespace and truncate text."""
    return " ".join(value.split())[:max_chars]


def slugify(value: str, *, fallback: str = "trace") -> str:
    """Create a filesystem-friendly slug."""
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return slug[:80] or fallback


def _build_screenshot_path(directory: str | Path, tool_name: str, label: str) -> Path:
    slug = slugify(f"{tool_name}-{label}")
    return Path(directory).expanduser() / f"{slug}-{uuid4().hex[:8]}.png"


__all__ = [
    "DEFAULT_PLAYWRIGHT_TOOL_TIMEOUT_MS",
    "DEFAULT_SCREENSHOT_DIR",
    "PlaywrightFlow",
    "PlaywrightToolSpec",
    "PlaywrightToolTrace",
    "click_first_visible",
    "compact_text",
    "first_attached_locator",
    "first_visible_locator",
    "navigate",
    "run_playwright_flow",
    "set_first_file_input",
    "slugify",
    "wait_for_load_state",
]
