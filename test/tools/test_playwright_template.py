"""Tests for reusable Playwright tool template helpers."""

from unittest import TestCase
from unittest.mock import patch

from agent.memory.models import MemoryRecord
from tools.playwright_template import (
    PlaywrightToolSpec,
    navigate,
    run_playwright_flow,
    wait_for_load_state,
)


class FakeTemplatePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.goto_calls = []
        self.load_state_calls = []
        self.screenshot_calls = []

    def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.url = url
        self.goto_calls.append((url, wait_until, timeout))

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.load_state_calls.append((state, timeout))

    def screenshot(self, path: str, full_page: bool) -> None:
        self.screenshot_calls.append((path, full_page))

    def content(self) -> str:
        return "<html><body>Jobs</body></html>"


class FakeTemplateContext:
    def __init__(self, page: FakeTemplatePage) -> None:
        self.page = page

    def new_page(self) -> FakeTemplatePage:
        return self.page


class FakeTemplateBrowser:
    def __init__(self, page: FakeTemplatePage) -> None:
        self.page = page
        self.closed = False
        self.context_kwargs = None

    def new_context(self, **kwargs):
        self.context_kwargs = kwargs
        return FakeTemplateContext(self.page)

    def close(self) -> None:
        self.closed = True


class FakeTemplateBrowserType:
    def __init__(self, browser: FakeTemplateBrowser) -> None:
        self.browser = browser

    def launch(self, headless: bool):
        self.headless = headless
        return self.browser


class FakeTemplatePlaywright:
    def __init__(self, browser_type: FakeTemplateBrowserType) -> None:
        self.chromium = browser_type


class FakeTemplateManager:
    def __init__(self, browser_type: FakeTemplateBrowserType) -> None:
        self.playwright = FakeTemplatePlaywright(browser_type)

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class PlaywrightTemplateTest(TestCase):
    def test_run_playwright_flow_records_trace_memory(self) -> None:
        page = FakeTemplatePage()
        browser = FakeTemplateBrowser(page)
        browser_type = FakeTemplateBrowserType(browser)
        spec = PlaywrightToolSpec(
            tool_name="test-browser-tool",
            task="Open test page",
            start_url="https://example.com",
            module="test_browser",
            tags=["unit"],
            session_state_path=".auth/linkedin.json",
            headless=True,
            capture_screenshot=True,
            capture_dom_snapshot=True,
        )
        record = MemoryRecord(
            module="test_browser",
            kind="browser_trace",
            task="Open test page",
            summary="ok",
        )

        def flow(active_page, trace):
            navigate(active_page, trace, "https://example.com")
            wait_for_load_state(active_page, trace)
            trace.add_extracted_data("items", [{"title": "AI Engineer"}])
            return {
                "status": "ok",
                "success": True,
                "message": "done",
            }

        with patch(
            "tools.playwright_template.record_browser_trace_safely",
            return_value=record,
        ) as record_mock:
            result = run_playwright_flow(
                spec,
                flow,
                playwright_factory=lambda: FakeTemplateManager(browser_type),
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["memory_record_id"], record.id)
        self.assertTrue(browser.closed)
        self.assertTrue(page.screenshot_calls)
        self.assertEqual(browser.context_kwargs["storage_state"].endswith(".auth/linkedin.json"), True)
        record_mock.assert_called_once()
        self.assertEqual(record_mock.call_args.kwargs["module"], "test_browser")
        self.assertIn("test-browser-tool", record_mock.call_args.kwargs["tags"])
        self.assertEqual(
            record_mock.call_args.kwargs["extracted_data"]["items"][0]["title"],
            "AI Engineer",
        )

    def test_run_playwright_flow_allows_memory_routing_override(self) -> None:
        page = FakeTemplatePage()
        browser = FakeTemplateBrowser(page)
        browser_type = FakeTemplateBrowserType(browser)
        spec = PlaywrightToolSpec(
            tool_name="test-browser-tool",
            task="Open ATS",
            start_url="https://example.com",
            module="test_browser",
            tags=["unit"],
        )
        record = MemoryRecord(
            module="job_application_greenhouse",
            kind="browser_trace",
            task="Open ATS",
            summary="ok",
        )

        def flow(active_page, trace):
            navigate(active_page, trace, "https://boards.greenhouse.io/acme/jobs/1")
            return {
                "status": "ok",
                "success": True,
                "message": "done",
                "memory_module": "job_application_greenhouse",
                "memory_tags": ["test-browser-tool", "platform-greenhouse"],
                "memory_metadata": {"application_platform": "greenhouse"},
            }

        with patch(
            "tools.playwright_template.record_browser_trace_safely",
            return_value=record,
        ) as record_mock:
            result = run_playwright_flow(
                spec,
                flow,
                playwright_factory=lambda: FakeTemplateManager(browser_type),
            )

        self.assertEqual(result["memory_record_id"], record.id)
        self.assertEqual(
            record_mock.call_args.kwargs["module"],
            "job_application_greenhouse",
        )
        self.assertIn("platform-greenhouse", record_mock.call_args.kwargs["tags"])
        self.assertEqual(
            record_mock.call_args.kwargs["metadata"]["application_platform"],
            "greenhouse",
        )
