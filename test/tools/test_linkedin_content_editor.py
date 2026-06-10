"""Tests for the LinkedIn content editor tool."""

from unittest import TestCase
from unittest.mock import patch

from tools.linkedin.content_editor import (
    DEFAULT_LINKEDIN_SESSION_STATE_PATH,
    LinkedInEditorInput,
    linkedin_editor,
)


class LinkedInContentEditorToolTest(TestCase):
    def test_tool_is_registered_with_expected_name(self) -> None:
        self.assertEqual(linkedin_editor.name, "linkedin-editor")

    def test_input_schema_uses_safe_defaults(self) -> None:
        tool_input = LinkedInEditorInput(task="Draft a launch post.")

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
            result = linkedin_editor.invoke({"task": "Draft an OfferGraph launch post."})

        self.assertEqual(result["status"], "needs_approval")
        self.assertEqual(result["url"], "https://www.linkedin.com/feed/")
        self.assertEqual(result["approval"]["mode"], "approve-mode")
        self.assertIn("Approval is required", result["message"])

    def test_auto_mode_bypasses_auth_approval_gate(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=False):
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "execution_mode": "auto-mode",
                }
            )

        self.assertEqual(result["status"], "planned")
        self.assertIn("auto-mode bypassed", result["message"])

    def test_invocation_returns_planned_status_when_auth_exists(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True):
            result = linkedin_editor.invoke({"task": "Draft an OfferGraph launch post."})

        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["url"], "https://www.linkedin.com/feed/")
        self.assertIn("linkedin-editor is defined", result["message"])

    def test_publish_conflicts_with_draft_only(self) -> None:
        result = linkedin_editor.invoke(
            {
                "task": "Publish an OfferGraph launch post.",
                "draft_only": True,
                "publish": True,
            }
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("conflicts", result["message"])

    def test_publish_without_draft_only_requests_confirmation(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=True):
            result = linkedin_editor.invoke(
                {
                    "task": "Publish an OfferGraph launch post.",
                    "draft_only": False,
                    "publish": True,
                }
            )

        self.assertEqual(result["status"], "needs_confirmation")
        self.assertIn("not implemented yet", result["message"])

    def test_invalid_execution_mode_returns_error(self) -> None:
        with patch("tools.linkedin.content_editor.Path.exists", return_value=False):
            result = linkedin_editor.invoke(
                {
                    "task": "Draft an OfferGraph launch post.",
                    "execution_mode": "bad-mode",
                }
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid tool execution mode", result["message"])
