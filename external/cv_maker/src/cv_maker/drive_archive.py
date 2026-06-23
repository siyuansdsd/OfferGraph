"""
Archive generated CV files to Google Drive through rclone.

The project deliberately delegates Google Drive authentication and upload
transport to rclone. That keeps OAuth credentials out of the app and gives the
CLI a stable, scriptable Google Drive backend.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_CONTENT = PROJECT_ROOT / "user_content"
GENERATED_DIR = USER_CONTENT / "generated_cvs"
ARCHIVE_MANIFEST_FILE = USER_CONTENT / "drive_archive_manifest.json"
DEFAULT_DATE_VALUE = "yesterday"
DEFAULT_MIN_ARCHIVE_AGE_DAYS = 2
ARCHIVABLE_EXTENSIONS = {".docx", ".pdf", ".tex"}


Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class ArchiveFile:
    name: str
    local_path: str
    remote_path: str
    download_link: str
    size: int
    mtime: str
    deleted: bool


@dataclass
class ArchiveResult:
    date: str
    archived_at: str
    remote_dir: str
    dry_run: bool
    files: list[ArchiveFile]


def parse_archive_date(value: str | None = None) -> date:
    raw = (value or DEFAULT_DATE_VALUE).strip().lower()
    today = datetime.now().date()
    if raw in {"", "yesterday", "prev", "previous"}:
        return today - timedelta(days=1)
    if raw == "today":
        return today
    return date.fromisoformat(raw)


def rclone_join(base: str, *parts: str) -> str:
    cleaned = str(base or "").rstrip("/")
    suffix = "/".join(str(part).strip("/") for part in parts if str(part).strip("/"))
    return f"{cleaned}/{suffix}" if suffix else cleaned


def default_remote() -> str:
    remote = (
        os.environ.get("GOOGLE_DRIVE_ARCHIVE_REMOTE")
        or os.environ.get("CV_ARCHIVE_REMOTE")
        or ""
    ).strip()
    if not remote:
        raise ValueError(
            "Missing Google Drive archive remote. Set GOOGLE_DRIVE_ARCHIVE_REMOTE "
            "in .env, for example: GOOGLE_DRIVE_ARCHIVE_REMOTE=gdrive:CV Maker Archive"
        )
    return remote


def _relative(path: Path | str) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def generated_files_for_date(target: date, source_dir: Path = GENERATED_DIR) -> list[Path]:
    if not source_dir.exists():
        return []

    files: list[Path] = []
    for path in source_dir.iterdir():
        if not path.is_file():
            continue
        if path.name == "mcdowellcv.cls":
            continue
        if path.suffix.lower() not in ARCHIVABLE_EXTENSIONS:
            continue
        if datetime.fromtimestamp(path.stat().st_mtime).date() == target:
            files.append(path)
    return sorted(files, key=lambda item: item.name.lower())


def generated_file_dates_before(cutoff: date, source_dir: Path = GENERATED_DIR) -> list[date]:
    if not source_dir.exists():
        return []

    dates: set[date] = set()
    for path in source_dir.iterdir():
        if not path.is_file():
            continue
        if path.name == "mcdowellcv.cls":
            continue
        if path.suffix.lower() not in ARCHIVABLE_EXTENSIONS:
            continue
        file_date = datetime.fromtimestamp(path.stat().st_mtime).date()
        if file_date < cutoff:
            dates.add(file_date)
    return sorted(dates)


def _run_rclone(
    args: list[str],
    *,
    rclone_path: str,
    runner: Runner,
) -> subprocess.CompletedProcess:
    command = [rclone_path, *args]
    try:
        return runner(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"rclone failed: {' '.join(command)}\n{details}") from exc


def _load_manifest(path: Path = ARCHIVE_MANIFEST_FILE) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("archives"), list):
                return data
    except Exception:
        pass
    return {"archives": []}


def _save_manifest(payload: dict[str, Any], path: Path = ARCHIVE_MANIFEST_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_archive_manifest(path: Path = ARCHIVE_MANIFEST_FILE) -> dict[str, Any]:
    return _load_manifest(path)


def archive_lookup_by_local_path(path: Path = ARCHIVE_MANIFEST_FILE) -> dict[str, dict[str, Any]]:
    manifest = _load_manifest(path)
    lookup: dict[str, dict[str, Any]] = {}
    for archive in manifest.get("archives", []):
        if not isinstance(archive, dict):
            continue
        for item in archive.get("files", []):
            if isinstance(item, dict) and item.get("local_path"):
                lookup[str(item["local_path"])] = {
                    **item,
                    "archive_date": archive.get("date", ""),
                    "remote_dir": archive.get("remote_dir", ""),
                }
    return lookup


def _merge_archive_result(result: ArchiveResult, manifest_file: Path) -> None:
    manifest = _load_manifest(manifest_file)
    archives = manifest.setdefault("archives", [])
    existing = None
    for archive in archives:
        if (
            isinstance(archive, dict)
            and archive.get("date") == result.date
            and archive.get("remote_dir") == result.remote_dir
        ):
            existing = archive
            break

    result_payload = {
        "date": result.date,
        "archived_at": result.archived_at,
        "remote_dir": result.remote_dir,
        "dry_run": result.dry_run,
        "files": [item.__dict__ for item in result.files],
    }

    if existing is None:
        archives.append(result_payload)
    else:
        by_path = {
            str(item.get("local_path")): item
            for item in existing.get("files", [])
            if isinstance(item, dict)
        }
        for item in result_payload["files"]:
            by_path[item["local_path"]] = item
        existing.update(result_payload)
        existing["files"] = list(by_path.values())

    archives.sort(key=lambda item: str(item.get("date", "")), reverse=True)
    _save_manifest(manifest, manifest_file)


def archive_generated_files(
    *,
    target_date: date | None = None,
    remote: str | None = None,
    source_dir: Path = GENERATED_DIR,
    manifest_file: Path = ARCHIVE_MANIFEST_FILE,
    delete_local: bool = True,
    dry_run: bool = False,
    rclone_path: str = "rclone",
    runner: Runner = subprocess.run,
    require_rclone: bool = True,
) -> ArchiveResult:
    target = target_date or parse_archive_date()
    drive_remote = remote or default_remote()
    remote_dir = rclone_join(drive_remote, target.isoformat())
    files = generated_files_for_date(target, source_dir)

    if require_rclone and not dry_run and not shutil.which(rclone_path):
        raise RuntimeError(
            "rclone is required for Google Drive archive upload. Install it with "
            "`brew install rclone`, then run `rclone config` and set "
            "GOOGLE_DRIVE_ARCHIVE_REMOTE in .env."
        )

    archived_files: list[ArchiveFile] = []
    archived_at = datetime.now().replace(microsecond=0).isoformat()

    if not dry_run and files:
        _run_rclone(["mkdir", remote_dir], rclone_path=rclone_path, runner=runner)

    for local_path in files:
        stat = local_path.stat()
        remote_path = rclone_join(remote_dir, local_path.name)
        download_link = ""
        deleted = False

        if not dry_run:
            _run_rclone(["copyto", str(local_path), remote_path], rclone_path=rclone_path, runner=runner)
            link_result = _run_rclone(["link", remote_path], rclone_path=rclone_path, runner=runner)
            download_link = (link_result.stdout or "").strip().splitlines()[-1].strip()
            if not download_link:
                raise RuntimeError(f"rclone uploaded {local_path.name} but returned no download link.")
            if delete_local:
                local_path.unlink()
                deleted = True

        archived_file = ArchiveFile(
            name=local_path.name,
            local_path=_relative(local_path),
            remote_path=remote_path,
            download_link=download_link,
            size=stat.st_size,
            mtime=datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat(),
            deleted=deleted,
        )
        archived_files.append(archived_file)

        if not dry_run:
            _merge_archive_result(
                ArchiveResult(
                    date=target.isoformat(),
                    archived_at=archived_at,
                    remote_dir=remote_dir,
                    dry_run=dry_run,
                    files=[archived_file],
                ),
                manifest_file,
            )

    result = ArchiveResult(
        date=target.isoformat(),
        archived_at=archived_at,
        remote_dir=remote_dir,
        dry_run=dry_run,
        files=archived_files,
    )

    if archived_files and not dry_run:
        _merge_archive_result(result, manifest_file)

    return result


def archive_generated_files_before(
    *,
    cutoff_date: date | None = None,
    remote: str | None = None,
    source_dir: Path = GENERATED_DIR,
    manifest_file: Path = ARCHIVE_MANIFEST_FILE,
    delete_local: bool = True,
    dry_run: bool = False,
    rclone_path: str = "rclone",
    runner: Runner = subprocess.run,
    require_rclone: bool = True,
) -> list[ArchiveResult]:
    cutoff = cutoff_date or datetime.now().date()
    targets = generated_file_dates_before(cutoff, source_dir)
    return [
        archive_generated_files(
            target_date=target,
            remote=remote,
            source_dir=source_dir,
            manifest_file=manifest_file,
            delete_local=delete_local,
            dry_run=dry_run,
            rclone_path=rclone_path,
            runner=runner,
            require_rclone=require_rclone,
        )
        for target in targets
    ]


def archive_generated_files_at_least_days_old(
    *,
    min_age_days: int = DEFAULT_MIN_ARCHIVE_AGE_DAYS,
    today: date | None = None,
    remote: str | None = None,
    source_dir: Path = GENERATED_DIR,
    manifest_file: Path = ARCHIVE_MANIFEST_FILE,
    delete_local: bool = True,
    dry_run: bool = False,
    rclone_path: str = "rclone",
    runner: Runner = subprocess.run,
    require_rclone: bool = True,
) -> list[ArchiveResult]:
    if min_age_days < 1:
        raise ValueError("min_age_days must be at least 1.")

    reference_date = today or datetime.now().date()
    cutoff_date = reference_date - timedelta(days=min_age_days - 1)
    return archive_generated_files_before(
        cutoff_date=cutoff_date,
        remote=remote,
        source_dir=source_dir,
        manifest_file=manifest_file,
        delete_local=delete_local,
        dry_run=dry_run,
        rclone_path=rclone_path,
        runner=runner,
        require_rclone=require_rclone,
    )


def _print_result(result: ArchiveResult) -> None:
    print(f"Archive date: {result.date}")
    print(f"Remote dir: {result.remote_dir}")
    print(f"Files archived: {len(result.files)}")
    for item in result.files:
        marker = "deleted" if item.deleted else "kept"
        link = f" -> {item.download_link}" if item.download_link else ""
        print(f"  - {item.name} ({marker}){link}")


def _print_results(results: list[ArchiveResult]) -> None:
    total = sum(len(result.files) for result in results)
    print(f"Archive batches: {len(results)}")
    print(f"Files archived: {total}")
    for result in results:
        _print_result(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Archive generated CV files to Google Drive using rclone.")
    parser.add_argument("--date", default=DEFAULT_DATE_VALUE, help="Date to archive: yesterday, today, or YYYY-MM-DD.")
    parser.add_argument("--before-today", action="store_true", help="Archive every generated file dated before today, grouped by file date.")
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        metavar="DAYS",
        help="Archive files at least DAYS old, grouped by file date. Use 2 to archive two days ago and older.",
    )
    parser.add_argument("--remote", default=None, help="Google Drive rclone destination, e.g. gdrive:CV Maker Archive.")
    parser.add_argument("--source-dir", default=str(GENERATED_DIR), help="Local generated files directory.")
    parser.add_argument("--manifest", default=str(ARCHIVE_MANIFEST_FILE), help="Local archive link manifest JSON path.")
    parser.add_argument("--keep-local", action="store_true", help="Upload and save links, but do not delete local files.")
    parser.add_argument("--dry-run", action="store_true", help="Show which files would be archived without uploading/deleting.")
    parser.add_argument("--rclone", default="rclone", help="rclone executable path.")
    args = parser.parse_args(argv)

    try:
        if args.older_than_days is not None:
            results = archive_generated_files_at_least_days_old(
                min_age_days=args.older_than_days,
                remote=args.remote,
                source_dir=Path(args.source_dir),
                manifest_file=Path(args.manifest),
                delete_local=not args.keep_local,
                dry_run=args.dry_run,
                rclone_path=args.rclone,
            )
            _print_results(results)
        elif args.before_today:
            results = archive_generated_files_before(
                remote=args.remote,
                source_dir=Path(args.source_dir),
                manifest_file=Path(args.manifest),
                delete_local=not args.keep_local,
                dry_run=args.dry_run,
                rclone_path=args.rclone,
            )
            _print_results(results)
        else:
            result = archive_generated_files(
                target_date=parse_archive_date(args.date),
                remote=args.remote,
                source_dir=Path(args.source_dir),
                manifest_file=Path(args.manifest),
                delete_local=not args.keep_local,
                dry_run=args.dry_run,
                rclone_path=args.rclone,
            )
            _print_result(result)
        return 0
    except Exception as exc:
        print(f"Archive failed: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
