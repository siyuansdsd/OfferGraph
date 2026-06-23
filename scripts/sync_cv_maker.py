"""Sync an external CV Maker checkout into OfferGraph's embedded runtime."""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CV_MAKER_PROJECT_ROOT = PROJECT_ROOT / "external" / "cv_maker"
DEFAULT_CV_MAKER_USER_CONTENT_DIR = (
    PROJECT_ROOT / "local_data" / "cv_maker" / "user_content"
)
CV_MAKER_USER_CONTENT_DIRS = (
    "library",
    "templates",
    "inputs",
    "generated_cvs",
    "logs",
)
CODE_EXCLUDES = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".DS_Store",
    ".env",
    "user_content",
)
USER_CONTENT_EXCLUDES = (
    ".DS_Store",
    "__pycache__",
    "*.pyc",
)


@dataclass
class SyncStats:
    copied: int = 0
    overwritten: int = 0
    skipped_existing: int = 0
    skipped_excluded: int = 0
    directories: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy CV Maker source into external/cv_maker and private "
            "user_content into local_data/cv_maker/user_content."
        )
    )
    parser.add_argument(
        "source_root",
        nargs="?",
        default=os.getenv("CV_MAKER_SOURCE_PROJECT_ROOT"),
        help=(
            "Path to the full CV Maker checkout. If omitted, "
            "CV_MAKER_SOURCE_PROJECT_ROOT is used."
        ),
    )
    parser.add_argument(
        "--project-root",
        default=os.getenv("CV_MAKER_PROJECT_ROOT", "external/cv_maker"),
        help="Destination for vendored CV Maker code.",
    )
    parser.add_argument(
        "--user-content-dir",
        default=os.getenv(
            "CV_MAKER_USER_CONTENT_DIR",
            "local_data/cv_maker/user_content",
        ),
        help="Destination for private CV Maker user_content.",
    )
    parser.add_argument(
        "--skip-code",
        action="store_true",
        help="Only sync user_content.",
    )
    parser.add_argument(
        "--skip-user-content",
        action="store_true",
        help="Only sync code.",
    )
    parser.add_argument(
        "--overwrite-user-content",
        action="store_true",
        help="Overwrite matching files in local user_content.",
    )
    parser.add_argument(
        "--init-only",
        action="store_true",
        help="Create the private user_content structure and symlink without syncing files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be copied without changing files.",
    )
    return parser.parse_args(argv)


def resolve_project_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser()
    if resolved.is_absolute():
        return resolved
    return PROJECT_ROOT / resolved


def validate_source_root(source_root: Path) -> None:
    if not source_root.exists():
        raise FileNotFoundError(f"CV Maker source root not found: {source_root}")
    if not (source_root / "run.py").exists():
        raise FileNotFoundError(f"CV Maker run.py not found: {source_root / 'run.py'}")
    if not (source_root / "src" / "cv_maker").exists():
        raise FileNotFoundError(
            f"CV Maker src/cv_maker not found: {source_root / 'src' / 'cv_maker'}"
        )


def sync_tree(
    source: Path,
    destination: Path,
    *,
    exclude_patterns: tuple[str, ...],
    overwrite_existing: bool,
    dry_run: bool = False,
) -> SyncStats:
    stats = SyncStats()
    if not source.exists():
        raise FileNotFoundError(f"Source path not found: {source}")
    if not dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    _copy_children(
        source,
        destination,
        source,
        exclude_patterns=exclude_patterns,
        overwrite_existing=overwrite_existing,
        dry_run=dry_run,
        stats=stats,
    )
    return stats


def ensure_user_content_structure(
    user_content_dir: Path,
    *,
    dry_run: bool = False,
) -> None:
    if dry_run:
        return
    user_content_dir.mkdir(parents=True, exist_ok=True)
    for relative_dir in CV_MAKER_USER_CONTENT_DIRS:
        (user_content_dir / relative_dir).mkdir(parents=True, exist_ok=True)


def _copy_children(
    source: Path,
    destination: Path,
    root: Path,
    *,
    exclude_patterns: tuple[str, ...],
    overwrite_existing: bool,
    dry_run: bool,
    stats: SyncStats,
) -> None:
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        rel_path = child.relative_to(root)
        if is_excluded(rel_path, exclude_patterns):
            stats.skipped_excluded += 1
            continue
        target = destination / child.name
        if child.is_dir():
            if not dry_run:
                target.mkdir(parents=True, exist_ok=True)
            stats.directories += 1
            _copy_children(
                child,
                target,
                root,
                exclude_patterns=exclude_patterns,
                overwrite_existing=overwrite_existing,
                dry_run=dry_run,
                stats=stats,
            )
            continue
        copy_file(
            child,
            target,
            overwrite_existing=overwrite_existing,
            dry_run=dry_run,
            stats=stats,
        )


def is_excluded(relative_path: Path, patterns: tuple[str, ...]) -> bool:
    parts = relative_path.parts
    return any(
        fnmatch.fnmatch(part, pattern)
        or fnmatch.fnmatch(str(relative_path), pattern)
        for part in parts
        for pattern in patterns
    )


def copy_file(
    source: Path,
    destination: Path,
    *,
    overwrite_existing: bool,
    dry_run: bool,
    stats: SyncStats,
) -> None:
    if destination.exists() and not overwrite_existing:
        stats.skipped_existing += 1
        return

    if destination.exists():
        stats.overwritten += 1
    else:
        stats.copied += 1

    if dry_run:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=True)


def ensure_user_content_link(
    project_root: Path,
    user_content_dir: Path,
    *,
    dry_run: bool = False,
) -> Path:
    link_path = project_root / "user_content"
    if dry_run:
        return link_path

    ensure_user_content_structure(user_content_dir)
    if link_path.is_symlink():
        if link_path.resolve() != user_content_dir.resolve():
            link_path.unlink()
            link_path.symlink_to(
                relative_symlink_target(user_content_dir, link_path.parent),
                target_is_directory=True,
            )
        return link_path

    if link_path.exists():
        raise FileExistsError(
            f"{link_path} exists and is not a symlink. Move private data to "
            f"{user_content_dir} before running this script."
        )

    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(
        relative_symlink_target(user_content_dir, link_path.parent),
        target_is_directory=True,
    )
    return link_path


def relative_symlink_target(target: Path, link_parent: Path) -> Path:
    return Path(os.path.relpath(target.resolve(), link_parent.resolve()))


def sync_cv_maker(
    source_root: Path,
    project_root: Path,
    user_content_dir: Path,
    *,
    skip_code: bool = False,
    skip_user_content: bool = False,
    overwrite_user_content: bool = False,
    dry_run: bool = False,
) -> dict[str, SyncStats]:
    validate_source_root(source_root)
    results: dict[str, SyncStats] = {}
    if not skip_code:
        results["code"] = sync_tree(
            source_root,
            project_root,
            exclude_patterns=CODE_EXCLUDES,
            overwrite_existing=True,
            dry_run=dry_run,
        )
    if not skip_user_content:
        results["user_content"] = sync_tree(
            source_root / "user_content",
            user_content_dir,
            exclude_patterns=USER_CONTENT_EXCLUDES,
            overwrite_existing=overwrite_user_content,
            dry_run=dry_run,
        )
    ensure_user_content_link(project_root, user_content_dir, dry_run=dry_run)
    return results


def format_stats(label: str, stats: SyncStats) -> str:
    return (
        f"{label}: copied={stats.copied}, overwritten={stats.overwritten}, "
        f"skipped_existing={stats.skipped_existing}, "
        f"skipped_excluded={stats.skipped_excluded}, directories={stats.directories}"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = resolve_project_path(args.project_root).resolve()
    user_content_dir = resolve_project_path(args.user_content_dir).resolve()

    if args.init_only:
        ensure_user_content_link(project_root, user_content_dir, dry_run=args.dry_run)
        print(f"Embedded runtime: {project_root}")
        print(f"Private user_content: {user_content_dir}")
        print("Initialized CV Maker user_content structure.")
        if args.dry_run:
            print("dry-run: no files changed")
        return 0

    if not args.source_root:
        print(
            "source_root is required unless CV_MAKER_SOURCE_PROJECT_ROOT is set.",
            file=sys.stderr,
        )
        return 2

    source_root = Path(args.source_root).expanduser().resolve()

    try:
        results = sync_cv_maker(
            source_root,
            project_root,
            user_content_dir,
            skip_code=args.skip_code,
            skip_user_content=args.skip_user_content,
            overwrite_user_content=args.overwrite_user_content,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"CV Maker source: {source_root}")
    print(f"Embedded runtime: {project_root}")
    print(f"Private user_content: {user_content_dir}")
    for label, stats in results.items():
        print(format_stats(label, stats))
    if args.dry_run:
        print("dry-run: no files changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
