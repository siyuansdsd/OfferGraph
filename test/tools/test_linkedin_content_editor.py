"""Tests for the LinkedIn content editor tool."""

from unittest import TestCase

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
        self.assertEqual(
            tool_input.session_state_path,
            DEFAULT_LINKEDIN_SESSION_STATE_PATH,
        )

    def test_default_invocation_returns_planned_status(self) -> None:
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
        result = linkedin_editor.invoke(
            {
                "task": "Publish an OfferGraph launch post.",
                "draft_only": False,
                "publish": True,
            }
        )

        self.assertEqual(result["status"], "needs_confirmation")
        self.assertIn("not implemented yet", result["message"])
