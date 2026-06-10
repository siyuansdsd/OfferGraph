"""Tests for reusable tool approval gates."""

from unittest import TestCase
from unittest.mock import patch

from tools.approval import (
    APPROVE_MODE,
    AUTO_MODE,
    TOOL_EXECUTION_MODE_ENV,
    ApprovalRequest,
    get_tool_execution_mode,
    request_user_approval,
)


class ApprovalTest(TestCase):
    def setUp(self) -> None:
        self.request = ApprovalRequest(
            action="linkedin-auth-setup",
            reason="LinkedIn needs a saved browser session.",
            automated_flow="Open a browser and save storage state.",
            manual_steps=["Log in manually."],
        )

    def test_default_mode_is_approve_mode(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_tool_execution_mode(), APPROVE_MODE)

    def test_env_can_enable_auto_mode(self) -> None:
        with patch.dict("os.environ", {TOOL_EXECUTION_MODE_ENV: AUTO_MODE}):
            self.assertEqual(get_tool_execution_mode(), AUTO_MODE)

    def test_auto_mode_approves_without_prompt(self) -> None:
        decision = request_user_approval(self.request, mode=AUTO_MODE)

        self.assertTrue(decision.approved)
        self.assertEqual(decision.status, "approved")

    def test_approve_mode_non_interactive_requests_approval(self) -> None:
        decision = request_user_approval(self.request, mode=APPROVE_MODE)

        self.assertFalse(decision.approved)
        self.assertEqual(decision.status, "needs_approval")
        self.assertEqual(decision.manual_steps, ["Log in manually."])

    def test_approve_mode_interactive_can_be_approved(self) -> None:
        decision = request_user_approval(
            self.request,
            mode=APPROVE_MODE,
            interactive=True,
            input_func=lambda _: "yes",
        )

        self.assertTrue(decision.approved)
        self.assertEqual(decision.status, "approved")

    def test_approve_mode_interactive_can_fall_back_to_manual(self) -> None:
        decision = request_user_approval(
            self.request,
            mode=APPROVE_MODE,
            interactive=True,
            input_func=lambda _: "no",
        )

        self.assertFalse(decision.approved)
        self.assertEqual(decision.status, "manual_required")
