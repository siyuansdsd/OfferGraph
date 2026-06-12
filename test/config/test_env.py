"""Tests for project environment helpers."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from config.env import get_env, load_project_env, require_env


class EnvTest(TestCase):
    def test_load_project_env_reads_env_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text("TAVILY_API_KEY=test-tavily\n", encoding="utf-8")

            with patch.dict("os.environ", {}, clear=True):
                self.assertTrue(load_project_env(env_file))
                self.assertEqual(get_env("TAVILY_API_KEY", load=False), "test-tavily")

    def test_get_env_uses_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch(
            "config.env.load_project_env",
            return_value=False,
        ):
            self.assertEqual(get_env("MISSING_KEY", "fallback"), "fallback")

    def test_require_env_raises_for_missing_value(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch(
            "config.env.load_project_env",
            return_value=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "MISSING_KEY"):
                require_env("MISSING_KEY")
