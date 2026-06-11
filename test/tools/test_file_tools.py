"""Tests for virtual file-system tools."""

from unittest import TestCase

from tools.file_tools import ls, read_file, write_file


class FileToolsTest(TestCase):
    def test_ls_returns_sorted_files(self) -> None:
        result = ls.func({"files": {"b.md": "B", "a.md": "A"}})

        self.assertEqual(result, ["a.md", "b.md"])

    def test_read_file_returns_numbered_lines(self) -> None:
        result = read_file.func(
            "notes.md",
            {"files": {"notes.md": "first\nsecond\nthird"}},
            1,
            1,
        )

        self.assertEqual(result, "     2\tsecond")

    def test_read_file_handles_missing_file(self) -> None:
        result = read_file.func("missing.md", {"files": {}}, 0, 10)

        self.assertIn("not found", result)

    def test_write_file_returns_command_update(self) -> None:
        command = write_file.func("notes.md", "content", {"files": {}}, "call-1")

        self.assertEqual(command.update["files"], {"notes.md": "content"})
        self.assertEqual(command.update["messages"][0].tool_call_id, "call-1")
