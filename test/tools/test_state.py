"""Tests for shared Plan Master state helpers."""

from unittest import TestCase

from tools.state import file_reducer


class StateTest(TestCase):
    def test_file_reducer_handles_none(self) -> None:
        self.assertEqual(file_reducer(None, {"a.md": "A"}), {"a.md": "A"})
        self.assertEqual(file_reducer({"a.md": "A"}, None), {"a.md": "A"})

    def test_file_reducer_merges_with_right_precedence(self) -> None:
        result = file_reducer({"a.md": "old", "b.md": "B"}, {"a.md": "new"})

        self.assertEqual(result, {"a.md": "new", "b.md": "B"})
