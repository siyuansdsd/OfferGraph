"""Tests for TODO tools."""

from unittest import TestCase

from tools.todo_tools import read_todos, write_todos


class TodoToolsTest(TestCase):
    def test_write_todos_returns_command_update(self) -> None:
        todos = [{"content": "Research market", "status": "pending"}]

        command = write_todos.func(todos, "call-1")

        self.assertEqual(command.update["todos"], todos)
        self.assertEqual(command.update["messages"][0].tool_call_id, "call-1")

    def test_read_todos_handles_empty_list(self) -> None:
        result = read_todos.func({"todos": []}, "call-1")

        self.assertEqual(result, "No todos currently in the list.")

    def test_read_todos_formats_items(self) -> None:
        result = read_todos.func(
            {"todos": [{"content": "Research market", "status": "in_progress"}]},
            "call-1",
        )

        self.assertIn("Current TODO List:", result)
        self.assertIn("[in_progress] Research market", result)
