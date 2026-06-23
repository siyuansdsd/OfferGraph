"""Tests for the CV Maker sync helper."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.sync_cv_maker import (
    CV_MAKER_USER_CONTENT_DIRS,
    ensure_user_content_link,
    ensure_user_content_structure,
    main,
    sync_cv_maker,
    sync_tree,
)


class SyncCvMakerTest(TestCase):
    def test_sync_tree_skips_existing_when_requested(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            destination = root / "destination"
            (source / "library").mkdir(parents=True)
            (source / "library" / "master.pdf").write_text("source", encoding="utf-8")
            (destination / "library").mkdir(parents=True)
            (destination / "library" / "master.pdf").write_text(
                "local",
                encoding="utf-8",
            )

            stats = sync_tree(
                source,
                destination,
                exclude_patterns=(),
                overwrite_existing=False,
            )

            self.assertEqual(stats.skipped_existing, 1)
            self.assertEqual(
                (destination / "library" / "master.pdf").read_text(encoding="utf-8"),
                "local",
            )

    def test_sync_cv_maker_excludes_source_user_content_from_runtime(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source_cv"
            project_root = root / "external" / "cv_maker"
            user_content_dir = root / "local_data" / "cv_maker" / "user_content"

            (source / "src" / "cv_maker").mkdir(parents=True)
            (source / "user_content" / "library").mkdir(parents=True)
            (source / "run.py").write_text("print('run')\n", encoding="utf-8")
            (source / "src" / "cv_maker" / "__init__.py").write_text(
                "",
                encoding="utf-8",
            )
            (source / "user_content" / "library" / "master.pdf").write_text(
                "pdf",
                encoding="utf-8",
            )

            sync_cv_maker(source, project_root, user_content_dir)

            self.assertTrue((project_root / "run.py").exists())
            self.assertTrue((project_root / "user_content").is_symlink())
            self.assertTrue((user_content_dir / "library" / "master.pdf").exists())

    def test_ensure_user_content_structure_creates_required_directories(self) -> None:
        with TemporaryDirectory() as temp_dir:
            user_content_dir = Path(temp_dir) / "user_content"

            ensure_user_content_structure(user_content_dir)

            for relative_dir in CV_MAKER_USER_CONTENT_DIRS:
                self.assertTrue((user_content_dir / relative_dir).is_dir())

    def test_main_init_only_does_not_require_source_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "external" / "cv_maker"
            user_content_dir = root / "local_data" / "cv_maker" / "user_content"

            with redirect_stdout(StringIO()):
                exit_code = main(
                    [
                        "--init-only",
                        "--project-root",
                        str(project_root),
                        "--user-content-dir",
                        str(user_content_dir),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((project_root / "user_content").is_symlink())
            for relative_dir in CV_MAKER_USER_CONTENT_DIRS:
                self.assertTrue((user_content_dir / relative_dir).is_dir())

    def test_ensure_user_content_link_repoints_existing_symlink(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "external" / "cv_maker"
            old_content = root / "old_content"
            user_content_dir = root / "local_data" / "cv_maker" / "user_content"
            project_root.mkdir(parents=True)
            old_content.mkdir()
            (project_root / "user_content").symlink_to(old_content)

            ensure_user_content_link(project_root, user_content_dir)

            self.assertEqual(
                (project_root / "user_content").resolve(),
                user_content_dir.resolve(),
            )
