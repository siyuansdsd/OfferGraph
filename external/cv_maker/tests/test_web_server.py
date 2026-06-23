import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cv_maker import web_server


class TestWebServerData(unittest.TestCase):
    def test_parse_token_usage_supports_minimax_anthropic_logs(self):
        log_text = (
            "2026-05-22 13:45:08,594 - cv_maker.llm_client - INFO - "
            "MiniMax tokens: usage={'input_tokens': 241, 'output_tokens': 291, "
            "'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 6}\n"
        )

        usage = web_server.parse_token_usage(log_text)

        self.assertEqual(usage["totals"]["input"], 247)
        self.assertEqual(usage["totals"]["output"], 291)
        self.assertEqual(usage["totals"]["total"], 538)
        self.assertEqual(usage["daily"]["2026-05-22"], 538)

    def test_list_applications_discovers_generated_tex_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated_cvs"
            generated.mkdir()
            (generated / "Acme_AI_Engineer.tex").write_text(
                "\\begin{cvsection}{Executive Summary}\n"
                "\\begin{cvsubsection}{}{}{}\n"
                "Builds AI systems.\n"
                "\\end{cvsubsection}\n"
                "\\end{cvsection}\n",
                encoding="utf-8",
            )
            (generated / "Acme_AI_Engineer.pdf").write_bytes(b"%PDF")
            manifest = root / "applications.json"

            with patch.multiple(
                web_server,
                GENERATED_DIR=generated,
                APPLICATIONS_FILE=manifest,
                PROJECT_ROOT=root.resolve(),
            ):
                records = web_server.list_applications()

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["company"], "Acme")
            self.assertEqual(records[0]["role"], "AI Engineer")
            self.assertIn("Builds AI systems.", records[0]["jd_summary"])
            self.assertEqual(records[0]["files"]["pdf"], "generated_cvs/Acme_AI_Engineer.pdf")

    def test_update_application_status_persists_discovered_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated_cvs"
            generated.mkdir()
            (generated / "Acme_AI_Engineer.tex").write_text("content", encoding="utf-8")
            manifest = root / "applications.json"

            with patch.multiple(
                web_server,
                GENERATED_DIR=generated,
                APPLICATIONS_FILE=manifest,
                PROJECT_ROOT=root.resolve(),
            ):
                record = web_server.update_application_status("discovered-Acme_AI_Engineer", "Applied")
                records = web_server.list_applications()

            self.assertEqual(record["status"], "Applied")
            self.assertEqual(records[0]["status"], "Applied")

    def test_list_applications_attaches_archive_links_for_deleted_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            generated = root / "generated_cvs"
            generated.mkdir()
            manifest = root / "applications.json"
            archive_manifest = root / "drive_archive_manifest.json"
            manifest.write_text(
                """
                {
                  "applications": [
                    {
                      "id": "app-1",
                      "created_at": "2026-05-22T10:00:00",
                      "role": "AI Engineer",
                      "files": {"pdf": "generated_cvs/AI_Engineer.pdf"}
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            archive_manifest.write_text(
                """
                {
                  "archives": [
                    {
                      "date": "2026-05-21",
                      "remote_dir": "gdrive:CV/2026-05-21",
                      "files": [
                        {
                          "name": "AI_Engineer.pdf",
                          "local_path": "generated_cvs/AI_Engineer.pdf",
                          "remote_path": "gdrive:CV/2026-05-21/AI_Engineer.pdf",
                          "download_link": "https://drive.google.com/mock"
                        }
                      ]
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )

            with patch.multiple(
                web_server,
                GENERATED_DIR=generated,
                APPLICATIONS_FILE=manifest,
                ARCHIVE_MANIFEST_FILE=archive_manifest,
                PROJECT_ROOT=root,
            ):
                records = web_server.list_applications()

            self.assertEqual(
                records[0]["archived_files"]["pdf"]["download_link"],
                "https://drive.google.com/mock",
            )

    def test_run_archive_old_files_defaults_to_two_day_minimum_age(self):
        result = web_server.drive_archive.ArchiveResult(
            date="2026-05-21",
            archived_at="2026-05-23T10:00:00",
            remote_dir="gdrive:CV/2026-05-21",
            dry_run=False,
            files=[],
        )

        with patch.object(
            web_server.drive_archive,
            "archive_generated_files_at_least_days_old",
            return_value=[result],
        ) as archive:
            payload = web_server.run_archive_old_files({"remote": "gdrive:CV"})

        self.assertEqual(payload["batches"][0]["date"], "2026-05-21")
        archive.assert_called_once()
        self.assertEqual(archive.call_args.kwargs["min_age_days"], 2)
        self.assertEqual(archive.call_args.kwargs["remote"], "gdrive:CV")


if __name__ == "__main__":
    unittest.main()
