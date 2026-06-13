"""Tests for agent model selection helpers."""

from unittest import TestCase
from unittest.mock import Mock, patch

from agent.model_selection import (
    CONSOLE_MODEL_ENV,
    DEFAULT_CONSOLE_MODEL_CHOICE,
    DEFAULT_MODEL_CHOICE,
    MINIMAX_API_KEY_ENV,
    MINIMAX_MAX_TOKENS,
    create_minimax_model,
    get_console_model_choice,
    get_minimax_key,
    list_console_model_choices,
    resolve_model_reference,
)


class ModelSelectionTest(TestCase):
    def test_list_console_model_choices_includes_default(self) -> None:
        self.assertIn(DEFAULT_CONSOLE_MODEL_CHOICE, list_console_model_choices())
        self.assertIn(DEFAULT_MODEL_CHOICE, list_console_model_choices())

    def test_get_console_model_choice_reads_env(self) -> None:
        with patch.dict("os.environ", {CONSOLE_MODEL_ENV: "MiniMax-M2.5"}), patch(
            "agent.model_selection.load_project_env",
            return_value=True,
        ):
            self.assertEqual(get_console_model_choice(), "MiniMax-M2.5")

    def test_get_minimax_key_reads_api_key_env(self) -> None:
        with patch.dict("os.environ", {MINIMAX_API_KEY_ENV: "test-key"}), patch(
            "agent.model_selection.load_project_env",
            return_value=True,
        ):
            self.assertEqual(get_minimax_key(), "test-key")

    def test_create_minimax_model_uses_api_key_env(self) -> None:
        fake_model = Mock()

        with patch.dict("os.environ", {MINIMAX_API_KEY_ENV: "test-key"}), patch(
            "agent.model_selection.load_project_env",
            return_value=True,
        ), patch("agent.model_selection.MiniMaxChat", return_value=fake_model) as chat_cls:
            model = create_minimax_model("MiniMax-M2.7")

        self.assertIs(model, fake_model)
        chat_cls.assert_called_once_with(
            api_key="test-key",
            model="MiniMax-M2.7",
            max_tokens=MINIMAX_MAX_TOKENS,
        )

    def test_create_minimax_model_requires_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch(
            "agent.model_selection.load_project_env",
            return_value=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "MINIMAX_API_KEY"):
                create_minimax_model("MiniMax-M2.7")

    def test_resolve_model_reference(self) -> None:
        fake_model = Mock()

        with patch(
            "agent.model_selection.create_minimax_model",
            return_value=fake_model,
        ) as create_mock:
            self.assertIs(resolve_model_reference("MiniMax-M2.5"), fake_model)

        create_mock.assert_called_once_with("MiniMax-M2.5")
        self.assertIsNone(resolve_model_reference(DEFAULT_MODEL_CHOICE))
        self.assertEqual(
            resolve_model_reference("openai:gpt-4o-mini"),
            "openai:gpt-4o-mini",
        )
        self.assertIs(resolve_model_reference(fake_model), fake_model)
