"""Tests for the LinkedIn editor smoke test script."""

from io import StringIO
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts.check_linkedin_editor import main, parse_args


class CheckLinkedInEditorScriptTest(TestCase):
    def test_parse_args_accepts_publish_alias(self) -> None:
        with patch(
            "sys.argv",
            ["check_linkedin_editor.py", "--post-text", "Final post text", "--publish"],
        ):
            args = parse_args()

        self.assertTrue(args.publish)

    def test_parse_args_accepts_legacy_publish_path_alias(self) -> None:
        with patch(
            "sys.argv",
            [
                "check_linkedin_editor.py",
                "--post-text",
                "Final post text",
                "--publish-path",
            ],
        ):
            args = parse_args()

        self.assertTrue(args.publish)

    def test_main_passes_publish_confirmation_path_to_tool(self) -> None:
        with patch(
            "sys.argv",
            [
                "check_linkedin_editor.py",
                "--task",
                "Post this draft",
                "--post-text",
                "Final post text",
                "--publish",
            ],
        ), patch("scripts.check_linkedin_editor.linkedin_editor") as editor_mock, patch(
            "sys.stdout",
            new_callable=StringIO,
        ):
            editor_mock.invoke = Mock(return_value={"status": "published"})

            exit_code = main()

        self.assertEqual(exit_code, 0)
        editor_mock.invoke.assert_called_once_with(
            {
                "task": "Post this draft",
                "post_text": "Final post text",
                "draft_only": False,
                "publish": True,
                "execution_mode": None,
            }
        )
