"""Tests for the LinkedIn content editor tool."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from tools.linkedin.content_editor import (
    COMPOSER_BUTTON_SELECTORS,
    COMPOSER_EDITOR_SELECTORS,
    DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    LinkedInDraftValidationError,
    POST_BUTTON_SELECTORS,
    LinkedInEditorBrowserError,
    LinkedInEditorInput,
    compose_post,
    confirm_linkedin_publish,
    linkedin_editor,
    open_linkedin_composer,
    record_linkedin_editor_memory,
)
from tools.linkedin.auth import LINKEDIN_FEED_URL


class FakeLocator:
    def __init__(self) -> None:
        self.clicked = False
        self.filled_text = None

    @property
    def first(self):
        return self

    def wait_for(self, state: str, timeout: int) -> None:
        self.wait_state = state
        self.wait_timeout = timeout

    def click(self) -> None:
        self.clicked = True

    def fill(self, text: str, timeout: int) -> None:
        self.filled_text = text
        self.fill_timeout = timeout


class FakePage:
    def __init__(self) -> None:
        self.url = LINKEDIN_FEED_URL
        self.goto_calls = []
        self.load_state_calls = []
        self.button = FakeLocator()
        self.editor = FakeLocator()
        self.post_button = FakeLocator()

    def goto(self, url: str, wait_until: str, timeout: int) -> None:
        self.goto_calls.append((url, wait_until, timeout))

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        self.load_state_calls.append((state, timeout))

    def locator(self, selector: str) -> FakeLocator:
        if selector == COMPOSER_BUTTON_SELECTORS[0]:
            return self.button
        if selector == COMPOSER_EDITOR_SELECTORS[0]:
            return self.editor
        if selector == POST_BUTTON_SELECTORS[0]:
            return self.post_button
        raise AssertionError(f"Unexpected selector: {selector}")


class FakeBrowser:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.closed = False
        self.context = Mock()
        self.context.new_page.return_value = page

    def new_context(self, storage_state: str):
        self.storage_state = storage_state
        return self.context

    def close(self) -> None:
        self.closed = True


class FakeBrowserType:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser

    def launch(self, headless: bool):
        self.headless = headless
        return self.browser


class FakePlaywrightManager:
    def __init__(self, browser_type: FakeBrowserType) -> None:
        self.playwright = Mock()
        self.playwright.chromium = browser_type

    def __enter__(self):
        return self.playwright

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class LinkedInContentEditorToolTest(TestCase):
    def test_tool_is_registered_with_expected_name(self) -> None:
        self.assertEqual(linkedin_editor.name, "linkedin-editor")

    def test_input_schema_uses_safe_defaults(self) -> None:
        tool_input = LinkedInEditorInput(
            task="Draft a launch post.",
            post_text="Final post text.",
        )

        self.assertTrue(tool_input.draft_only)
        self.assertFalse(tool_input.publish)
        self.assertFalse(tool_input.headless)
        self.assertIsNone(tool_input.execution_mode)
        self.assertEqual(
            tool_input.session_state_path,
            DEFAULT_LINKEDIN_SESSION_STATE_PATH,
        )

    def test_default_invocation_requests_approval_when_auth_is_missing(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=False):
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                }
            )

        self.assertEqual(result["status"], "needs_approval")
        self.assertEqual(result["url"], "https://www.linkedin.com/feed/")
        self.assertEqual(result["approval"]["mode"], "approve-mode")
        self.assertIn("Approval is required", result["message"])

    def test_auto_mode_returns_manual_steps_when_auth_is_missing(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=False):
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                    "execution_mode": "auto-mode",
                }
            )

        self.assertEqual(result["status"], "manual_required")
        self.assertEqual(result["approval"]["mode"], "auto-mode")
        self.assertFalse(result["approval"]["approved"])
        self.assertIn("auth state is missing", result["message"])
        self.assertIn("scripts/setup_linkedin_auth.py", result["approval"]["manual_steps"][1])

    def test_compose_post_prefers_post_text_as_exact_draft(self) -> None:
        self.assertEqual(compose_post("Final post text", task="Brief"), "Final post text")

    def test_compose_post_requires_final_post_text(self) -> None:
        with self.assertRaisesRegex(LinkedInDraftValidationError, "post_text"):
            compose_post("")

    def test_compose_post_rejects_task_brief(self) -> None:
        with self.assertRaisesRegex(LinkedInDraftValidationError, "task brief"):
            compose_post(
                "Create a LinkedIn post about MiniMax",
                task="Create a LinkedIn post about MiniMax",
            )

        with self.assertRaisesRegex(LinkedInDraftValidationError, "task brief"):
            compose_post(
                "Prepare a LinkedIn post draft about MiniMax AI revenue.",
                task="MiniMax post",
            )

    def test_invocation_opens_browser_and_returns_draft_ready_when_auth_exists(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.open_linkedin_composer",
            return_value={"url": LINKEDIN_FEED_URL},
        ) as open_mock, patch(
            "tools.linkedin.content_editor.record_linkedin_editor_memory",
        ) as memory_mock:
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                }
            )

        self.assertEqual(result["status"], "draft_ready")
        self.assertEqual(result["url"], LINKEDIN_FEED_URL)
        self.assertEqual(result["draft"], "Final post text")
        self.assertIn("left unpublished", result["message"])
        open_mock.assert_called_once_with(
            DEFAULT_LINKEDIN_SESSION_STATE_PATH,
            headless=False,
            draft="Final post text",
            publish=False,
        )
        memory_mock.assert_called_once()
        self.assertEqual(memory_mock.call_args.kwargs["status"], "draft_ready")
        self.assertTrue(memory_mock.call_args.kwargs["success"])

    def test_invocation_rejects_missing_final_post_text_before_opening_browser(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.open_linkedin_composer",
        ) as open_mock:
            result = linkedin_editor.invoke(
                {
                    "task": "Prepare a LinkedIn post draft about MiniMax AI.",
                    "post_text": "",
                }
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("final LinkedIn post text", result["message"])
        open_mock.assert_not_called()

    def test_publish_conflicts_with_draft_only(self) -> None:
        result = linkedin_editor.invoke(
            {
                "task": "Publish an OfferGraph launch post.",
                "post_text": "Final post text",
                "draft_only": True,
                "publish": True,
            }
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("conflicts", result["message"])

    def test_publish_without_draft_only_requests_confirmation(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.open_linkedin_composer",
            return_value={
                "url": LINKEDIN_FEED_URL,
                "published": False,
                "publish_confirmed": False,
            },
        ) as open_mock, patch(
            "tools.linkedin.content_editor.record_linkedin_editor_memory",
        ) as memory_mock:
            result = linkedin_editor.invoke(
                {
                    "task": "Publish an OfferGraph launch post.",
                    "post_text": "Final post text",
                    "draft_only": False,
                    "publish": True,
                }
            )

        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["draft"], "Final post text")
        self.assertIn("confirmation was not granted", result["message"])
        open_mock.assert_called_once_with(
            DEFAULT_LINKEDIN_SESSION_STATE_PATH,
            headless=False,
            draft="Final post text",
            publish=True,
        )
        memory_mock.assert_called_once()
        self.assertEqual(memory_mock.call_args.kwargs["status"], "needs_confirmation")

    def test_publish_path_returns_published_after_terminal_confirmation(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.open_linkedin_composer",
            return_value={
                "url": LINKEDIN_FEED_URL,
                "published": True,
                "publish_confirmed": True,
            },
        ), patch(
            "tools.linkedin.content_editor.record_linkedin_editor_memory",
        ) as memory_mock:
            result = linkedin_editor.invoke(
                {
                    "task": "Publish an OfferGraph launch post.",
                    "post_text": "Final post text",
                    "draft_only": False,
                    "publish": True,
                }
            )

        self.assertEqual(result["status"], "published")
        self.assertIn("posted after y/n confirmation", result["message"])
        memory_mock.assert_called_once()
        self.assertEqual(memory_mock.call_args.kwargs["status"], "published")

    def test_invalid_execution_mode_returns_error(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=False):
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                    "execution_mode": "bad-mode",
                }
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid tool execution mode", result["message"])

    def test_browser_error_returns_error_result(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.open_linkedin_composer",
            side_effect=LinkedInEditorBrowserError("Browser failed"),
        ), patch(
            "tools.linkedin.content_editor.record_linkedin_editor_memory",
        ) as memory_mock:
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                }
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("Browser failed", result["message"])
        self.assertEqual(result["draft"], "Final post text")
        memory_mock.assert_called_once()
        self.assertFalse(memory_mock.call_args.kwargs["success"])
        self.assertEqual(memory_mock.call_args.kwargs["error"], "Browser failed")

    def test_record_linkedin_editor_memory_sanitizes_browser_trace(self) -> None:
        with patch("tools.linkedin.content_editor.record_browser_trace_safely") as record_mock:
            record_linkedin_editor_memory(
                task="Draft post",
                draft="Final post text " * 80,
                browser_result={
                    "url": LINKEDIN_FEED_URL,
                    "composer_selector": COMPOSER_BUTTON_SELECTORS[0],
                    "editor_selector": COMPOSER_EDITOR_SELECTORS[0],
                    "draft_inserted": True,
                    "publish_requested": False,
                    "publish_confirmed": False,
                    "published": False,
                },
                status="draft_ready",
                message="Draft ready",
                publish=False,
                success=True,
            )

        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        self.assertEqual(kwargs["module"], "linkedin")
        self.assertEqual(kwargs["url"], LINKEDIN_FEED_URL)
        self.assertIn("linkedin-editor", kwargs["tags"])
        self.assertNotIn("session_state_path", kwargs["extracted_data"])
        self.assertLessEqual(len(kwargs["extracted_data"]["draft_preview"]), 500)

    def test_open_linkedin_composer_loads_auth_state_and_fills_draft(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            page = FakePage()
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)
            wait_for_user = Mock()

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                result = open_linkedin_composer(
                    str(state_path),
                    headless=True,
                    draft="Final post text",
                    wait_for_user=wait_for_user,
                )

        self.assertEqual(result["url"], LINKEDIN_FEED_URL)
        self.assertTrue(result["draft_inserted"])
        self.assertEqual(result["composer_selector"], COMPOSER_BUTTON_SELECTORS[0])
        self.assertEqual(result["editor_selector"], COMPOSER_EDITOR_SELECTORS[0])
        self.assertEqual(page.goto_calls[0][0], LINKEDIN_FEED_URL)
        self.assertEqual(browser.storage_state, str(state_path.resolve()))
        self.assertTrue(page.button.clicked)
        self.assertEqual(page.editor.filled_text, "Final post text")
        self.assertFalse(page.post_button.clicked)
        self.assertTrue(browser.closed)
        wait_for_user.assert_not_called()

    def test_open_linkedin_composer_clicks_post_after_yes_confirmation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            page = FakePage()
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)
            confirm_publish = Mock(return_value="y")

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                result = open_linkedin_composer(
                    str(state_path),
                    headless=True,
                    draft="Final post text",
                    publish=True,
                    confirm_publish=confirm_publish,
                )

        self.assertTrue(result["publish_requested"])
        self.assertTrue(result["publish_confirmed"])
        self.assertTrue(result["published"])
        self.assertEqual(result["post_selector"], POST_BUTTON_SELECTORS[0])
        self.assertTrue(page.post_button.clicked)
        confirm_publish.assert_called_once()

    def test_open_linkedin_composer_does_not_post_after_no_confirmation(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            page = FakePage()
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)
            confirm_publish = Mock(return_value="n")

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                result = open_linkedin_composer(
                    str(state_path),
                    headless=True,
                    draft="Final post text",
                    publish=True,
                    confirm_publish=confirm_publish,
                )

        self.assertTrue(result["publish_requested"])
        self.assertFalse(result["publish_confirmed"])
        self.assertFalse(result["published"])
        self.assertIsNone(result["post_selector"])
        self.assertFalse(page.post_button.clicked)
        confirm_publish.assert_called_once()

    def test_open_linkedin_composer_waits_for_visible_review(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            page = FakePage()
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)
            wait_for_user = Mock(return_value="")

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                open_linkedin_composer(
                    str(state_path),
                    headless=False,
                    draft="Final post text",
                    wait_for_user=wait_for_user,
                )

        wait_for_user.assert_called_once()

    def test_confirm_linkedin_publish_accepts_only_yes(self) -> None:
        self.assertTrue(confirm_linkedin_publish(lambda _: "y"))
        self.assertTrue(confirm_linkedin_publish(lambda _: "yes"))
        self.assertFalse(confirm_linkedin_publish(lambda _: "n"))
        self.assertFalse(confirm_linkedin_publish(lambda _: ""))
