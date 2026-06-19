"""Tests for the LinkedIn content editor tool."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from playwright.sync_api import Error as PlaywrightError

from tools.linkedin.content_editor import (
    COMPOSER_BUTTON_SELECTORS,
    COMPOSER_EDITOR_SELECTORS,
    DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    LinkedInDraftValidationError,
    MEDIA_BUTTON_SELECTORS,
    MEDIA_FILE_INPUT_SELECTORS,
    MEDIA_FINALIZE_BUTTON_SELECTORS,
    MEDIA_PREVIEW_SELECTORS,
    POST_BUTTON_SELECTORS,
    LinkedInEditorBrowserError,
    LinkedInEditorInput,
    _PREPARED_DRAFT_KEYS,
    compose_post,
    confirm_linkedin_publish,
    linkedin_editor,
    open_linkedin_composer,
    record_linkedin_editor_memory,
    resolve_linkedin_image_upload_path,
)
from tools.linkedin.auth import LINKEDIN_FEED_URL


class FakeLocator:
    def __init__(self, *, fail_attached: bool = False) -> None:
        self.clicked = False
        self.filled_text = None
        self.input_files = None
        self.fail_attached = fail_attached
        self.bounding_box_calls = 0

    @property
    def first(self):
        return self

    def wait_for(self, state: str, timeout: int) -> None:
        if self.fail_attached and state == "attached":
            raise PlaywrightError("not attached")
        self.wait_state = state
        self.wait_timeout = timeout

    def click(self) -> None:
        self.clicked = True

    def fill(self, text: str, timeout: int) -> None:
        self.filled_text = text
        self.fill_timeout = timeout

    def set_input_files(self, files: str) -> None:
        self.input_files = files

    def bounding_box(self, timeout: int | None = None) -> dict[str, float]:
        self.bounding_box_calls += 1
        self.bounding_box_timeout = timeout
        return {"x": 100.0, "y": 50.0, "width": 80.0, "height": 30.0}


class FakeMouse:
    def __init__(self) -> None:
        self.moves = []

    def move(self, x: float, y: float, steps: int | None = None) -> None:
        self.moves.append((x, y, steps))


class FakeFileChooser:
    def __init__(self) -> None:
        self.files = None

    def set_files(self, files: str) -> None:
        self.files = files


class FakeFileChooserContext:
    def __init__(self, file_chooser: FakeFileChooser) -> None:
        self.value = file_chooser

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class FakePage:
    def __init__(self, *, file_input_attached: bool = True) -> None:
        self.url = LINKEDIN_FEED_URL
        self.goto_calls = []
        self.load_state_calls = []
        self.button = FakeLocator()
        self.editor = FakeLocator()
        self.post_button = FakeLocator()
        self.media_button = FakeLocator()
        self.file_input = FakeLocator(fail_attached=not file_input_attached)
        self.media_preview = FakeLocator()
        self.media_finalize_button = FakeLocator()
        self.file_chooser = FakeFileChooser()
        self.mouse = FakeMouse()
        self.evaluate_calls = []
        self.timeout_calls = []

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
        if selector == MEDIA_BUTTON_SELECTORS[0]:
            return self.media_button
        if selector in MEDIA_FILE_INPUT_SELECTORS:
            return self.file_input
        if selector == MEDIA_PREVIEW_SELECTORS[0]:
            return self.media_preview
        if selector == MEDIA_FINALIZE_BUTTON_SELECTORS[0]:
            return self.media_finalize_button
        raise AssertionError(f"Unexpected selector: {selector}")

    def expect_file_chooser(self, timeout: int):
        self.file_chooser_timeout = timeout
        return FakeFileChooserContext(self.file_chooser)

    def evaluate(self, script: str, arg=None):
        self.evaluate_calls.append((script, arg))
        return True

    def wait_for_timeout(self, timeout: int) -> None:
        self.timeout_calls.append(timeout)


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
    def setUp(self) -> None:
        _PREPARED_DRAFT_KEYS.clear()

    def test_tool_is_registered_with_expected_name(self) -> None:
        self.assertEqual(linkedin_editor.name, "linkedin-editor")

    def test_input_schema_uses_safe_defaults(self) -> None:
        tool_input = LinkedInEditorInput(
            task="Draft a launch post.",
            post_text="Final post text.",
        )

        self.assertTrue(tool_input.draft_only)
        self.assertFalse(tool_input.publish)
        self.assertIsNone(tool_input.image_path)
        self.assertIsNone(tool_input.image_url)
        self.assertIsNone(tool_input.alt_text)
        self.assertTrue(tool_input.auto_image)
        self.assertTrue(tool_input.require_image)
        self.assertTrue(tool_input.show_cursor)
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
                    "auto_image": False,
                    "require_image": False,
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
                    "auto_image": False,
                    "require_image": False,
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
            image_path=None,
            alt_text=None,
            show_cursor=True,
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
                    "auto_image": False,
                    "require_image": False,
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
                "auto_image": False,
                "require_image": False,
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
                    "auto_image": False,
                    "require_image": False,
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
            image_path=None,
            alt_text=None,
            show_cursor=True,
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
                    "auto_image": False,
                    "require_image": False,
                }
            )

        self.assertEqual(result["status"], "published")
        self.assertIn("posted after y/n confirmation", result["message"])
        memory_mock.assert_called_once()
        self.assertEqual(memory_mock.call_args.kwargs["status"], "published")

    def test_invocation_passes_image_path_to_browser(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image-bytes")
            with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
                "tools.linkedin.content_editor.open_linkedin_composer",
                return_value={
                    "url": LINKEDIN_FEED_URL,
                    "image_uploaded": True,
                    "image_path": str(image_path.resolve()),
                },
            ) as open_mock, patch(
                "tools.linkedin.content_editor.record_linkedin_editor_memory",
            ):
                result = linkedin_editor.invoke(
                    {
                        "task": "Draft an OfferGraph launch post.",
                        "post_text": "Final post text",
                        "image_path": str(image_path),
                        "alt_text": "OfferGraph launch visual",
                        "auto_image": False,
                    }
                )

        self.assertEqual(result["status"], "draft_ready")
        self.assertEqual(result["image_path"], str(image_path.resolve()))
        open_mock.assert_called_once_with(
            DEFAULT_LINKEDIN_SESSION_STATE_PATH,
            headless=False,
            draft="Final post text",
            publish=False,
            image_path=str(image_path.resolve()),
            alt_text="OfferGraph launch visual",
            show_cursor=True,
        )

    def test_invocation_downloads_image_url_before_opening_browser(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.download_image_url",
            return_value=Path("/tmp/downloaded.png"),
        ) as download_mock, patch(
            "tools.linkedin.content_editor.open_linkedin_composer",
            return_value={
                "url": LINKEDIN_FEED_URL,
                "image_uploaded": True,
                "image_path": "/tmp/downloaded.png",
            },
        ) as open_mock, patch(
            "tools.linkedin.content_editor.record_linkedin_editor_memory",
        ):
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                    "image_url": "https://example.com/image.png",
                    "auto_image": False,
                }
            )

        self.assertEqual(result["image_path"], "/tmp/downloaded.png")
        download_mock.assert_called_once_with(
            "https://example.com/image.png",
            filename_hint="linkedin_editor_upload",
        )
        self.assertEqual(open_mock.call_args.kwargs["image_path"], "/tmp/downloaded.png")

    def test_invocation_auto_prepares_image_when_missing(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.prepare_linkedin_editor_image",
            return_value=(
                "/tmp/auto-image.png",
                {"source": "openai", "image_path": "/tmp/auto-image.png"},
            ),
        ) as prepare_mock, patch(
            "tools.linkedin.content_editor.open_linkedin_composer",
            return_value={
                "url": LINKEDIN_FEED_URL,
                "image_uploaded": True,
                "image_path": "/tmp/auto-image.png",
            },
        ) as open_mock, patch(
            "tools.linkedin.content_editor.record_linkedin_editor_memory",
        ) as memory_mock:
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                    "alt_text": "OfferGraph image",
                }
            )

        self.assertEqual(result["status"], "draft_ready")
        self.assertEqual(result["image_path"], "/tmp/auto-image.png")
        prepare_mock.assert_called_once_with(
            task="Draft an OfferGraph launch post.",
            post_text="Final post text",
            alt_text="OfferGraph image",
        )
        self.assertEqual(open_mock.call_args.kwargs["image_path"], "/tmp/auto-image.png")
        self.assertEqual(memory_mock.call_args.kwargs["image_preparation"]["source"], "openai")

    def test_invocation_returns_error_when_required_image_is_missing(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True), patch(
            "tools.linkedin.content_editor.prepare_linkedin_editor_image",
            return_value=(None, {"errors": ["no image available"]}),
        ), patch("tools.linkedin.content_editor.open_linkedin_composer") as open_mock:
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "post_text": "Final post text",
                }
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("could not prepare", result["message"])
        self.assertIn("no image available", result["message"])
        open_mock.assert_not_called()

    def test_prepare_linkedin_editor_image_uses_search_before_generation(self) -> None:
        with patch(
            "tools.linkedin.content_editor.run_tavily_image_search",
            return_value={"images": ["https://example.com/minimax-m3-image.png"]},
        ) as search_mock, patch(
            "tools.linkedin.content_editor.download_image_url",
            return_value=Path("/tmp/search-image.png"),
        ) as download_mock, patch(
            "tools.linkedin.content_editor.generate_openai_image",
        ) as generate_mock:
            from tools.linkedin.content_editor import prepare_linkedin_editor_image

            image_path, metadata = prepare_linkedin_editor_image(
                task="MiniMax M3 post",
                post_text="Final post text",
                alt_text="MiniMax M3 visual",
            )

        self.assertEqual(image_path, "/tmp/search-image.png")
        self.assertEqual(metadata["source"], "tavily")
        search_mock.assert_called_once()
        download_mock.assert_called_once()
        generate_mock.assert_not_called()

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
                    "auto_image": False,
                    "require_image": False,
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
                image_path="/tmp/image.png",
                alt_text="Alt text",
            )

        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        self.assertEqual(kwargs["module"], "linkedin")
        self.assertEqual(kwargs["url"], LINKEDIN_FEED_URL)
        self.assertIn("linkedin-editor", kwargs["tags"])
        self.assertNotIn("session_state_path", kwargs["extracted_data"])
        self.assertEqual(kwargs["extracted_data"]["image_path"], "/tmp/image.png")
        self.assertLessEqual(len(kwargs["extracted_data"]["draft_preview"]), 500)

    def test_resolve_linkedin_image_upload_path_validates_local_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image-bytes")

            resolved = resolve_linkedin_image_upload_path(image_path=str(image_path))

        self.assertEqual(resolved, str(image_path.resolve()))

    def test_resolve_linkedin_image_upload_path_downloads_url(self) -> None:
        with patch(
            "tools.linkedin.content_editor.download_image_url",
            return_value=Path("/tmp/downloaded.png"),
        ) as download_mock:
            resolved = resolve_linkedin_image_upload_path(
                image_url="https://example.com/image.png"
            )

        self.assertEqual(resolved, "/tmp/downloaded.png")
        download_mock.assert_called_once_with(
            "https://example.com/image.png",
            filename_hint="linkedin_editor_upload",
        )

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

    def test_open_linkedin_composer_uploads_image(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image-bytes")
            page = FakePage()
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                result = open_linkedin_composer(
                    str(state_path),
                    headless=True,
                    draft="Final post text",
                    image_path=str(image_path),
                )

        self.assertTrue(result["image_uploaded"])
        self.assertEqual(result["image_path"], str(image_path.resolve()))
        self.assertFalse(page.media_button.clicked)
        self.assertEqual(page.file_input.input_files, str(image_path.resolve()))
        self.assertTrue(page.media_finalize_button.clicked)
        self.assertGreater(len(page.mouse.moves), 0)
        self.assertGreater(len(page.evaluate_calls), 0)
        self.assertEqual(result["image_upload"]["method"], "file_input")
        self.assertTrue(result["image_upload"]["preview_ready"])
        self.assertTrue(result["image_upload"]["finalized"])
        self.assertTrue(result["image_upload"]["post_review_ready"])

    def test_open_linkedin_composer_uses_file_chooser_when_input_is_not_attached(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image-bytes")
            page = FakePage(file_input_attached=False)
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                result = open_linkedin_composer(
                    str(state_path),
                    headless=True,
                    draft="Final post text",
                    image_path=str(image_path),
                )

        self.assertTrue(page.media_button.clicked)
        self.assertEqual(page.file_chooser.files, str(image_path.resolve()))
        self.assertEqual(result["image_upload"]["method"], "file_chooser")
        self.assertTrue(page.media_finalize_button.clicked)

    def test_open_linkedin_composer_confirms_publish_after_media_finalize(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            image_path = Path(tmp_dir) / "image.png"
            image_path.write_bytes(b"image-bytes")
            page = FakePage()
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)

            def confirm_publish(_: str) -> str:
                self.assertTrue(page.media_finalize_button.clicked)
                return "n"

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                result = open_linkedin_composer(
                    str(state_path),
                    headless=True,
                    draft="Final post text",
                    image_path=str(image_path),
                    publish=True,
                    confirm_publish=confirm_publish,
                )

        self.assertTrue(result["image_upload"]["finalized"])
        self.assertTrue(result["publish_requested"])
        self.assertFalse(result["publish_confirmed"])
        self.assertFalse(result["published"])

    def test_open_linkedin_composer_can_hide_visual_cursor(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            state_path.write_text("{}", encoding="utf-8")
            page = FakePage()
            browser = FakeBrowser(page)
            browser_type = FakeBrowserType(browser)

            with patch(
                "tools.linkedin.content_editor.sync_playwright",
                return_value=FakePlaywrightManager(browser_type),
            ):
                open_linkedin_composer(
                    str(state_path),
                    headless=True,
                    draft="Final post text",
                    show_cursor=False,
                )

        self.assertEqual(page.mouse.moves, [])
        self.assertEqual(page.evaluate_calls, [])

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
