import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cv_maker.env_loader import load_env_file


class TestEnvLoader(unittest.TestCase):
    def test_load_env_file_sets_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "MINIMAX_API_KEY=minimax-test\n"
                "MINIMAX_API_FORMAT=anthropic\n"
                "MINIMAX_BASE_URL=https://api.minimax.io/anthropic\n"
                "MINIMAX_MAX_TOKENS=32768\n"
                "CANDIDATE_ADDRESS=108 Talavera St, Macquarie University, NSW 2113\n"
                "CANDIDATE_WEBSITE=www.douglas-yang.com\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                load_env_file(env_path)

                self.assertEqual(os.environ["MINIMAX_API_KEY"], "minimax-test")
                self.assertEqual(os.environ["MINIMAX_API_FORMAT"], "anthropic")
                self.assertEqual(os.environ["MINIMAX_BASE_URL"], "https://api.minimax.io/anthropic")
                self.assertEqual(os.environ["MINIMAX_MAX_TOKENS"], "32768")
                self.assertEqual(os.environ["CANDIDATE_ADDRESS"], "108 Talavera St, Macquarie University, NSW 2113")
                self.assertEqual(os.environ["CANDIDATE_WEBSITE"], "www.douglas-yang.com")

    def test_load_env_file_does_not_override_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("OPENAI_API_KEY=from-file\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENAI_API_KEY": "from-shell"}, clear=True):
                load_env_file(env_path)

                self.assertEqual(os.environ["OPENAI_API_KEY"], "from-shell")


if __name__ == "__main__":
    unittest.main()
