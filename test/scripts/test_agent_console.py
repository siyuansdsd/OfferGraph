"""Tests for the agent console script."""

from unittest import TestCase
from unittest.mock import patch

from scripts.agent_console import (
    DEFAULT_CONSOLE_MODEL_CHOICE,
    choose_model,
    prompt_for_model_choice,
)


class AgentConsoleTest(TestCase):
    def test_choose_model_uses_argument(self) -> None:
        self.assertEqual(choose_model("MiniMax-M2.5"), "MiniMax-M2.5")

    def test_choose_model_uses_env_default_when_non_interactive(self) -> None:
        with patch("scripts.agent_console.sys.stdin.isatty", return_value=False), patch(
            "scripts.agent_console.get_console_model_choice",
            return_value="MiniMax-M2.5",
        ):
            self.assertEqual(choose_model(None), "MiniMax-M2.5")

    def test_prompt_for_model_choice_defaults_to_m27(self) -> None:
        with patch("builtins.input", return_value=""), patch("builtins.print"):
            self.assertEqual(prompt_for_model_choice(), DEFAULT_CONSOLE_MODEL_CHOICE)

    def test_prompt_for_model_choice_accepts_index(self) -> None:
        with patch("builtins.input", return_value="2"), patch("builtins.print"):
            self.assertEqual(prompt_for_model_choice(), "MiniMax-M2.5")
