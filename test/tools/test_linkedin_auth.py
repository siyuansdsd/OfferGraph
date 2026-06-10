"""Tests for LinkedIn auth helpers."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from tools.linkedin.auth import LINKEDIN_FEED_URL, setup_linkedin_auth_state


class LinkedInAuthTest(TestCase):
    def test_setup_auth_state_saves_storage_state_and_closes_browser(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / "linkedin.json"
            page = Mock()
            page.url = LINKEDIN_FEED_URL
            context = Mock()
            context.new_page.return_value = page
            browser = Mock()
            browser.new_context.return_value = context
            browser_type = Mock()
            browser_type.launch.return_value = browser
            playwright = Mock()
            playwright.chromium = browser_type
            manager = MagicMock()
            manager.__enter__.return_value = playwright
            manager.__exit__.return_value = None

            with patch("tools.linkedin.auth.sync_playwright", return_value=manager):
                saved_path, current_url = setup_linkedin_auth_state(
                    state_path=state_path,
                    browser_name="chromium",
                    wait_for_user=lambda _: "",
                )

            self.assertEqual(saved_path, state_path.resolve())
            self.assertEqual(current_url, LINKEDIN_FEED_URL)
            page.goto.assert_called_with(LINKEDIN_FEED_URL, wait_until="domcontentloaded")
            context.storage_state.assert_called_once_with(path=str(state_path.resolve()))
            browser.close.assert_called_once()
