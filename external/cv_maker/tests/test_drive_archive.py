import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from cv_maker import drive_archive


def _touch_day(path: Path, target: date) -> None:
    timestamp = datetime(target.year, target.month, target.day, 12, 0, 0).timestamp()
    os.utime(path, (timestamp, timestamp))


class TestDriveArchive(unittest.TestCase):
    def test_generated_files_for_date_filters_archivable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = date(2026, 5, 21)
            keep = root / "Role.pdf"
            skip_today = root / "Today.pdf"
            skip_cls = root / "mcdowellcv.cls"
            skip_log = root / "notes.log"

            for path in (keep, skip_today, skip_cls, skip_log):
                path.write_text("x", encoding="utf-8")
            _touch_day(keep, target)
            _touch_day(skip_cls, target)
            _touch_day(skip_log, target)
            _touch_day(skip_today, target + timedelta(days=1))

            files = drive_archive.generated_files_for_date(target, root)

            self.assertEqual(files, [keep])

    def test_archive_generated_files_uploads_links_and_deletes_local_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated"
            generated.mkdir()
            manifest = root / "manifest.json"
            target = date(2026, 5, 21)
            pdf = generated / "Acme_AI_Engineer.pdf"
            pdf.write_text("pdf", encoding="utf-8")
            _touch_day(pdf, target)
            calls = []

            def fake_runner(args, **kwargs):
                calls.append(args)
                stdout = "https://drive.google.com/mock\n" if args[1] == "link" else ""
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

            result = drive_archive.archive_generated_files(
                target_date=target,
                remote="gdrive:CV Maker Archive",
                source_dir=generated,
                manifest_file=manifest,
                runner=fake_runner,
                require_rclone=False,
            )

            self.assertFalse(pdf.exists())
            self.assertEqual(result.remote_dir, "gdrive:CV Maker Archive/2026-05-21")
            self.assertEqual(result.files[0].download_link, "https://drive.google.com/mock")
            self.assertIn(["rclone", "mkdir", "gdrive:CV Maker Archive/2026-05-21"], calls)
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(saved["archives"][0]["files"][0]["name"], "Acme_AI_Engineer.pdf")

    def test_archive_generated_files_dry_run_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated"
            generated.mkdir()
            target = date(2026, 5, 21)
            tex = generated / "Acme_AI_Engineer.tex"
            tex.write_text("tex", encoding="utf-8")
            _touch_day(tex, target)

            result = drive_archive.archive_generated_files(
                target_date=target,
                remote="gdrive:CV Maker Archive",
                source_dir=generated,
                manifest_file=root / "manifest.json",
                dry_run=True,
            )

            self.assertTrue(tex.exists())
            self.assertFalse(result.files[0].deleted)
            self.assertEqual(result.files[0].download_link, "")

    def test_archive_generated_files_before_groups_by_file_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated"
            generated.mkdir()
            manifest = root / "manifest.json"
            first = generated / "First.pdf"
            second = generated / "Second.docx"
            today = generated / "Today.pdf"
            for path in (first, second, today):
                path.write_text(path.name, encoding="utf-8")

            _touch_day(first, date(2026, 5, 20))
            _touch_day(second, date(2026, 5, 21))
            _touch_day(today, date(2026, 5, 22))
            calls = []

            def fake_runner(args, **kwargs):
                calls.append(args)
                stdout = f"https://drive.google.com/{args[-1].split('/')[-1]}\n" if args[1] == "link" else ""
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

            results = drive_archive.archive_generated_files_before(
                cutoff_date=date(2026, 5, 22),
                remote="gdrive:CV Maker Archive",
                source_dir=generated,
                manifest_file=manifest,
                runner=fake_runner,
                require_rclone=False,
            )

            self.assertEqual([result.date for result in results], ["2026-05-20", "2026-05-21"])
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(today.exists())
            self.assertIn(["rclone", "mkdir", "gdrive:CV Maker Archive/2026-05-20"], calls)
            self.assertIn(["rclone", "mkdir", "gdrive:CV Maker Archive/2026-05-21"], calls)

    def test_archive_generated_files_at_least_two_days_old_keeps_yesterday_and_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated"
            generated.mkdir()
            manifest = root / "manifest.json"
            three_days_old = generated / "ThreeDaysOld.pdf"
            two_days_old = generated / "TwoDaysOld.docx"
            yesterday = generated / "Yesterday.pdf"
            today_file = generated / "Today.pdf"
            for path in (three_days_old, two_days_old, yesterday, today_file):
                path.write_text(path.name, encoding="utf-8")

            today = date(2026, 5, 23)
            _touch_day(three_days_old, date(2026, 5, 20))
            _touch_day(two_days_old, date(2026, 5, 21))
            _touch_day(yesterday, date(2026, 5, 22))
            _touch_day(today_file, today)

            def fake_runner(args, **kwargs):
                stdout = f"https://drive.google.com/{args[-1].split('/')[-1]}\n" if args[1] == "link" else ""
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

            results = drive_archive.archive_generated_files_at_least_days_old(
                min_age_days=2,
                today=today,
                remote="gdrive:CV Maker Archive",
                source_dir=generated,
                manifest_file=manifest,
                runner=fake_runner,
                require_rclone=False,
            )

            self.assertEqual([result.date for result in results], ["2026-05-20", "2026-05-21"])
            self.assertFalse(three_days_old.exists())
            self.assertFalse(two_days_old.exists())
            self.assertTrue(yesterday.exists())
            self.assertTrue(today_file.exists())


if __name__ == "__main__":
    unittest.main()
