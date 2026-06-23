"""
Local web UI for driving the existing CV Maker CLI.

The web server intentionally calls run.py as a subprocess. That keeps the
command-line workflow as the single production path and avoids a second,
slightly different generation implementation.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from cv_maker import drive_archive


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_CONTENT = PROJECT_ROOT / "user_content"
GENERATED_DIR = USER_CONTENT / "generated_cvs"
INPUTS_DIR = USER_CONTENT / "inputs"
LOG_FILE = USER_CONTENT / "logs" / "cv.log"
APPLICATIONS_FILE = USER_CONTENT / "applications.json"
ARCHIVE_MANIFEST_FILE = USER_CONTENT / "drive_archive_manifest.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
STATUS_OPTIONS = ["Generated", "Applied", "Interview", "Rejected", "Offer", "Archived"]
_APPLY_LOCK = threading.Lock()
_ARCHIVE_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _json_default(value: Any) -> str:
    return str(value)


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _slug(value: str, fallback: str = "job") -> str:
    text = re.sub(r"[^\w\s-]", "", value or "", flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "_", text).strip("_")
    return (text or fallback)[:80]


def _relative(path: Path | str | None) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def _file_links(stem: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for suffix, label in ((".pdf", "pdf"), (".tex", "tex"), ("_CoverLetter.docx", "cover_letter")):
        path = GENERATED_DIR / f"{stem}{suffix}"
        if path.exists():
            files[label] = _relative(path)
    return files


def _title_from_stem(stem: str) -> tuple[str, str]:
    clean = stem.replace("_", " ").strip()
    if not clean:
        return "", "Generated CV"

    words = clean.split()
    if len(words) <= 2:
        return "", clean

    company_word_count = 1
    if len(words) >= 2 and words[1].lower() in {"tax", "robot", "group", "systems"}:
        company_word_count = 2
    company = " ".join(words[:company_word_count])
    role = " ".join(words[company_word_count:]) or clean
    return company, role


def _parse_tex_summary(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

    match = re.search(
        r"\\begin\{cvsection\}\{Executive Summary\}.*?\\begin\{cvsubsection\}\{\}\{\}\{\}\s*(.*?)\s*\\end\{cvsubsection\}",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return ""
    summary = re.sub(r"\s+", " ", match.group(1)).strip()
    return summary[:260]


def _application_sort_key(record: dict[str, Any]) -> str:
    return str(record.get("created_at") or record.get("date") or "")


def _load_manifest() -> dict[str, Any]:
    data = _read_json(APPLICATIONS_FILE, {"applications": []})
    if not isinstance(data, dict):
        return {"applications": []}
    apps = data.get("applications")
    if not isinstance(apps, list):
        data["applications"] = []
    return data


def _save_manifest(data: dict[str, Any]) -> None:
    _write_json(APPLICATIONS_FILE, data)


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    created_at = str(record.get("created_at") or _now_iso())
    date = created_at[:10]
    status = str(record.get("status") or "Generated")
    if status not in STATUS_OPTIONS:
        status = "Generated"

    return {
        "id": str(record.get("id") or _slug(f"{created_at}-{record.get('role', 'job')}")),
        "created_at": created_at,
        "date": str(record.get("date") or date),
        "company": str(record.get("company") or ""),
        "role": str(record.get("role") or "Generated CV"),
        "status": status,
        "jd_summary": str(record.get("jd_summary") or "JD summary unavailable for this historical file."),
        "key_skills": record.get("key_skills") if isinstance(record.get("key_skills"), list) else [],
        "jd_source": str(record.get("jd_source") or ""),
        "jd_input_path": str(record.get("jd_input_path") or ""),
        "output_stem": str(record.get("output_stem") or ""),
        "files": record.get("files") if isinstance(record.get("files"), dict) else {},
        "archived_files": record.get("archived_files") if isinstance(record.get("archived_files"), dict) else {},
        "tokens": record.get("tokens") if isinstance(record.get("tokens"), dict) else {"input": 0, "output": 0, "total": 0},
        "command": record.get("command") if isinstance(record.get("command"), list) else [],
        "returncode": int(record.get("returncode") or 0),
        "log_tail": str(record.get("log_tail") or ""),
    }


def _attach_archive_links(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lookup = drive_archive.archive_lookup_by_local_path(ARCHIVE_MANIFEST_FILE)
    for record in records:
        archived_files = dict(record.get("archived_files") or {})
        for label, rel_path in (record.get("files") or {}).items():
            if not rel_path:
                continue
            local_path = (PROJECT_ROOT / str(rel_path)).resolve()
            if local_path.exists():
                continue
            archived = lookup.get(str(rel_path))
            if archived:
                archived_files[str(label)] = archived
        record["archived_files"] = archived_files
    return records


def list_applications() -> list[dict[str, Any]]:
    manifest = _load_manifest()
    records = [_normalize_record(r) for r in manifest.get("applications", []) if isinstance(r, dict)]
    known_stems = {r.get("output_stem") for r in records if r.get("output_stem")}

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    for tex_path in GENERATED_DIR.glob("*.tex"):
        if tex_path.name == "mcdowellcv.cls":
            continue
        stem = tex_path.stem
        if stem in known_stems:
            continue
        company, role = _title_from_stem(stem)
        created_at = datetime.fromtimestamp(tex_path.stat().st_mtime).replace(microsecond=0).isoformat()
        records.append(
            _normalize_record(
                {
                    "id": f"discovered-{stem}",
                    "created_at": created_at,
                    "company": company,
                    "role": role,
                    "output_stem": stem,
                    "files": _file_links(stem),
                    "jd_summary": _parse_tex_summary(tex_path) or "Imported from generated files; original JD summary was not recorded.",
                }
            )
        )

    records.sort(key=_application_sort_key, reverse=True)
    return _attach_archive_links(records)


def update_application_status(record_id: str, status: str) -> dict[str, Any]:
    if status not in STATUS_OPTIONS:
        raise ValueError(f"Unsupported status: {status}")

    manifest = _load_manifest()
    apps = manifest.setdefault("applications", [])
    for index, record in enumerate(apps):
        if isinstance(record, dict) and str(record.get("id")) == record_id:
            record["status"] = status
            record["updated_at"] = _now_iso()
            apps[index] = record
            _save_manifest(manifest)
            return _normalize_record(record)

    discovered = next((r for r in list_applications() if r["id"] == record_id), None)
    if not discovered:
        raise KeyError(record_id)
    discovered["status"] = status
    discovered["updated_at"] = _now_iso()
    apps.append(discovered)
    _save_manifest(manifest)
    return discovered


def _parse_token_line(line: str) -> dict[str, int] | None:
    if " tokens:" not in line:
        return None

    usage_match = re.search(r"usage=(\{.*\})", line)
    if usage_match:
        try:
            usage = ast.literal_eval(usage_match.group(1))
        except Exception:
            usage = {}
        if isinstance(usage, dict):
            input_tokens = int(usage.get("input_tokens") or 0)
            input_tokens += int(usage.get("cache_creation_input_tokens") or 0)
            input_tokens += int(usage.get("cache_read_input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            return {
                "input": input_tokens,
                "output": output_tokens,
                "total": input_tokens + output_tokens,
            }

    compact = re.search(r"prompt=(\d+), completion=(\d+), total=(\d+)", line)
    if compact:
        return {
            "input": int(compact.group(1)),
            "output": int(compact.group(2)),
            "total": int(compact.group(3)),
        }
    return None


def parse_token_usage(log_text: str) -> dict[str, Any]:
    totals = {"input": 0, "output": 0, "total": 0, "calls": 0}
    daily: dict[str, int] = {}
    events: list[dict[str, Any]] = []

    for line in log_text.splitlines():
        parsed = _parse_token_line(line)
        if not parsed:
            continue
        date = line[:10] if re.match(r"\d{4}-\d{2}-\d{2}", line) else datetime.now().date().isoformat()
        totals["input"] += parsed["input"]
        totals["output"] += parsed["output"]
        totals["total"] += parsed["total"]
        totals["calls"] += 1
        daily[date] = daily.get(date, 0) + parsed["total"]
        events.append({"date": date, **parsed})

    return {"totals": totals, "daily": daily, "events": events[-60:]}


def read_token_usage() -> dict[str, Any]:
    try:
        return parse_token_usage(LOG_FILE.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {"totals": {"input": 0, "output": 0, "total": 0, "calls": 0}, "daily": {}, "events": []}


def _read_log_from(offset: int) -> str:
    try:
        with LOG_FILE.open("rb") as handle:
            handle.seek(offset)
            return handle.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _log_size() -> int:
    try:
        return LOG_FILE.stat().st_size
    except Exception:
        return 0


def _parse_run_metadata(text: str, stdout: str) -> dict[str, Any]:
    combined = f"{text}\n{stdout}"
    role = ""
    company = ""
    summary = ""
    skills: list[str] = []
    output_path = ""
    pdf_path = ""
    cover_path = ""

    match = re.search(r"analyze_job_description completed: .*?role='([^']*)', company='([^']*)'", combined)
    if match:
        role = match.group(1).strip()
        company = match.group(2).strip()

    match = re.search(r">\s*Target Role:\s*(.+)", combined)
    if match:
        summary = match.group(1).strip()

    match = re.search(r">\s*Key Skills:\s*(.+)", combined)
    if match:
        skills = [item.strip() for item in match.group(1).split(",") if item.strip()]

    match = re.search(r"Generating\s+\w+\s+to:\s*(\S+)", combined)
    if match:
        output_path = match.group(1).strip()

    match = re.search(r"(?:Tectonic PDF|LaTeX PDF) generated successfully:\s*(\S+)", combined)
    if match:
        pdf_path = match.group(1).strip()

    match = re.search(r"Cover Letter generated successfully:\s*(\S+)", combined)
    if match:
        cover_path = match.group(1).strip()

    output_stem = Path(output_path).stem if output_path else ""
    if not role and output_stem:
        company, role = _title_from_stem(output_stem)

    files: dict[str, str] = {}
    if output_path:
        suffix = Path(output_path).suffix.lower().lstrip(".") or "cv"
        files[suffix] = _relative(PROJECT_ROOT / output_path)
    if pdf_path:
        files["pdf"] = _relative(PROJECT_ROOT / pdf_path)
    if cover_path:
        files["cover_letter"] = _relative(PROJECT_ROOT / cover_path)
    if output_stem:
        files.update({k: v for k, v in _file_links(output_stem).items() if k not in files})

    return {
        "role": role or "Generated CV",
        "company": company,
        "jd_summary": summary or "Generated from the submitted JD.",
        "key_skills": skills,
        "output_stem": output_stem,
        "files": files,
    }


def _save_jd_text(jd_text: str) -> str:
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    preview = " ".join(jd_text.strip().split())[:60]
    filename = f"web_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_slug(preview, 'jd')}.txt"
    path = INPUTS_DIR / filename
    path.write_text(jd_text.strip() + "\n", encoding="utf-8")
    return _relative(path)


@dataclass
class ApplyResult:
    record: dict[str, Any]
    stdout: str
    stderr: str


def run_application(payload: dict[str, Any]) -> ApplyResult:
    jd = str(payload.get("jd") or "").strip()
    if not jd:
        raise ValueError("JD is required.")

    provider = str(payload.get("provider") or os.environ.get("CV_WEB_PROVIDER") or "minimax").strip()
    model = str(payload.get("model") or os.environ.get("CV_WEB_MODEL") or "MiniMax-M2.7").strip()
    output_format = str(payload.get("format") or os.environ.get("CV_WEB_FORMAT") or "latex").strip().lower()
    library = str(payload.get("library") or os.environ.get("CV_WEB_LIBRARY") or "user_content/library").strip()
    template = str(payload.get("template") or os.environ.get("CV_WEB_TEMPLATE") or "").strip()
    summarize = str(payload.get("summarize") or os.environ.get("CV_WEB_SUMMARIZE") or "10").strip()

    if output_format not in {"latex", "docx"}:
        raise ValueError("format must be latex or docx.")

    if re.match(r"^https?://", jd):
        jd_arg = jd
        jd_input_path = ""
    else:
        jd_input_path = _save_jd_text(jd)
        jd_arg = jd_input_path

    cmd = [
        sys.executable,
        "run.py",
        "--provider",
        provider,
        "--format",
        output_format,
        "--library",
        library,
        "--jd",
        jd_arg,
        "--summarize",
        summarize,
        "-vv",
    ]
    if model:
        cmd.extend(["--model", model])
    if template:
        cmd.extend(["--template", template])

    if not _APPLY_LOCK.acquire(blocking=False):
        raise RuntimeError("Another generation job is already running.")
    try:
        start_offset = _log_size()
        started = _now_iso()
        completed = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=int(os.environ.get("CV_WEB_TIMEOUT_SECONDS", "1200")),
        )
        new_log = _read_log_from(start_offset)
        metadata = _parse_run_metadata(new_log, completed.stdout)
        tokens = parse_token_usage(new_log)["totals"]

        record = _normalize_record(
            {
                "id": f"app-{datetime.now().strftime('%Y%m%d%H%M%S')}-{_slug(metadata['role'])}",
                "created_at": started,
                "company": metadata["company"],
                "role": metadata["role"],
                "status": "Generated" if completed.returncode == 0 else "Archived",
                "jd_summary": metadata["jd_summary"],
                "key_skills": metadata["key_skills"],
                "jd_source": jd if re.match(r"^https?://", jd) else "text",
                "jd_input_path": jd_input_path,
                "output_stem": metadata["output_stem"],
                "files": metadata["files"],
                "tokens": tokens,
                "command": cmd,
                "returncode": completed.returncode,
                "log_tail": (new_log + "\n" + completed.stdout + "\n" + completed.stderr)[-8000:],
            }
        )

        manifest = _load_manifest()
        manifest.setdefault("applications", []).append(record)
        _save_manifest(manifest)

        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or record["log_tail"]).strip()[-3000:])

        return ApplyResult(record=record, stdout=completed.stdout, stderr=completed.stderr)
    finally:
        _APPLY_LOCK.release()


def archive_payload() -> dict[str, Any]:
    manifest = drive_archive.read_archive_manifest(ARCHIVE_MANIFEST_FILE)
    archives = manifest.get("archives", []) if isinstance(manifest, dict) else []
    total_files = sum(
        len(item.get("files", []))
        for item in archives
        if isinstance(item, dict) and isinstance(item.get("files"), list)
    )
    try:
        remote = drive_archive.default_remote()
    except Exception:
        remote = ""
    return {
        "archives": archives,
        "default_remote": remote,
        "summary": {
            "folders": len(archives),
            "files": total_files,
        },
    }


def run_archive(payload: dict[str, Any]) -> dict[str, Any]:
    if not _ARCHIVE_LOCK.acquire(blocking=False):
        raise RuntimeError("Another archive job is already running.")
    try:
        target = drive_archive.parse_archive_date(str(payload.get("date") or "yesterday"))
        result = drive_archive.archive_generated_files(
            target_date=target,
            remote=str(payload.get("remote") or "").strip() or None,
            source_dir=GENERATED_DIR,
            manifest_file=ARCHIVE_MANIFEST_FILE,
            delete_local=not bool(payload.get("keep_local")),
            dry_run=bool(payload.get("dry_run")),
        )
        files = [item.__dict__ for item in result.files]
        return {
            "date": result.date,
            "archived_at": result.archived_at,
            "remote_dir": result.remote_dir,
            "dry_run": result.dry_run,
            "files": files,
            "log": "\n".join(
                [
                    f"Archive date: {result.date}",
                    f"Remote dir: {result.remote_dir}",
                    f"Files archived: {len(files)}",
                    *[
                        f"- {item['name']} -> {item.get('download_link') or item['remote_path']}"
                        for item in files
                    ],
                ]
            ),
        }
    finally:
        _ARCHIVE_LOCK.release()


def run_archive_old_files(payload: dict[str, Any]) -> dict[str, Any]:
    if not _ARCHIVE_LOCK.acquire(blocking=False):
        raise RuntimeError("Another archive job is already running.")
    try:
        min_age_days = int(payload.get("min_age_days") or drive_archive.DEFAULT_MIN_ARCHIVE_AGE_DAYS)
        results = drive_archive.archive_generated_files_at_least_days_old(
            min_age_days=min_age_days,
            remote=str(payload.get("remote") or "").strip() or None,
            source_dir=GENERATED_DIR,
            manifest_file=ARCHIVE_MANIFEST_FILE,
            delete_local=True,
            dry_run=False,
        )
        files = [
            item.__dict__
            for result in results
            for item in result.files
        ]
        return {
            "batches": [
                {
                    "date": result.date,
                    "archived_at": result.archived_at,
                    "remote_dir": result.remote_dir,
                    "dry_run": result.dry_run,
                    "files": [item.__dict__ for item in result.files],
                }
                for result in results
            ],
            "files": files,
            "log": "\n".join(
                [
                    f"Archive files at least {min_age_days} days old",
                    f"Batches: {len(results)}",
                    f"Files archived: {len(files)}",
                    *[
                        f"- {item['name']} -> {item.get('download_link') or item['remote_path']}"
                        for item in files
                    ],
                ]
            ),
        }
    finally:
        _ARCHIVE_LOCK.release()


def run_archive_before_today(payload: dict[str, Any]) -> dict[str, Any]:
    return run_archive_old_files(payload)


def _application_heatmap(records: list[dict[str, Any]], days: int = 365) -> list[dict[str, Any]]:
    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    counts: dict[str, int] = {}
    for record in records:
        date = str(record.get("date") or record.get("created_at", "")[:10])
        counts[date] = counts.get(date, 0) + 1

    total = sum(counts.values())
    active_days = len([value for value in counts.values() if value])
    average = total / active_days if active_days else 0
    cells = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        key = day.isoformat()
        count = counts.get(key, 0)
        if count == 0:
            level = 0
        elif average and count > average * 1.5:
            level = 4
        elif average and count > average:
            level = 3
        elif average and count >= average * 0.5:
            level = 2
        else:
            level = 1
        cells.append({"date": key, "count": count, "level": level})
    return cells


def dashboard_payload() -> dict[str, Any]:
    applications = list_applications()
    token_usage = read_token_usage()
    return {
        "applications": applications,
        "statuses": STATUS_OPTIONS,
        "summary": {
            "total": len(applications),
            "generated": len([r for r in applications if r.get("status") == "Generated"]),
            "applied": len([r for r in applications if r.get("status") == "Applied"]),
            "interview": len([r for r in applications if r.get("status") == "Interview"]),
        },
        "heatmap": {
            "month": _application_heatmap(applications, days=30),
            "year": _application_heatmap(applications, days=365),
        },
        "tokens": token_usage,
        "archives": archive_payload(),
    }


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CV Command Deck</title>
  <style>
    :root {
      --bg: #050806;
      --panel: #09110d;
      --panel2: #0d1621;
      --green: #39ff88;
      --green2: #0fbf68;
      --blue: #3da8ff;
      --blue2: #1464d2;
      --line: #1e4d3a;
      --text: #d9ffe8;
      --muted: #7faf9a;
      --danger: #ff5f7a;
      --shadow: #020402;
      --pixel: 4px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        linear-gradient(rgba(57,255,136,.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(61,168,255,.035) 1px, transparent 1px),
        radial-gradient(circle at 20% 0%, rgba(61,168,255,.12), transparent 32rem),
        var(--bg);
      background-size: 18px 18px, 18px 18px, auto, auto;
    }

    button, input, textarea, select {
      font: inherit;
    }

    .shell {
      width: min(1440px, calc(100vw - 28px));
      margin: 0 auto;
      padding: 22px 0 34px;
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
      border: var(--pixel) solid var(--green);
      background: #020604;
      box-shadow: 8px 8px 0 var(--shadow), inset 0 0 0 2px #123822;
      padding: 14px 16px;
    }

    .brand {
      display: grid;
      gap: 4px;
      min-width: 0;
    }

    .brand h1 {
      margin: 0;
      font-size: clamp(22px, 4vw, 40px);
      letter-spacing: 0;
      color: var(--green);
      text-transform: uppercase;
      line-height: 1;
    }

    .brand span {
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }

    .status-led {
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--blue);
      white-space: nowrap;
      font-size: 13px;
    }

    .led {
      width: 14px;
      height: 14px;
      background: var(--green);
      box-shadow: 0 0 14px var(--green);
      border: 2px solid #b6ffd2;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(340px, .85fr);
      gap: 16px;
      align-items: start;
    }

    .panel {
      border: var(--pixel) solid var(--line);
      background: rgba(9, 17, 13, .94);
      box-shadow: 8px 8px 0 var(--shadow);
      position: relative;
    }

    .panel.blue {
      border-color: var(--blue2);
      background: rgba(10, 18, 30, .94);
    }

    .panel-head {
      min-height: 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      border-bottom: var(--pixel) solid currentColor;
      color: var(--green);
      background: #030806;
    }

    .panel.blue .panel-head { color: var(--blue); }
    .panel-title {
      font-weight: 800;
      text-transform: uppercase;
      font-size: 15px;
      overflow-wrap: anywhere;
    }

    .pixel-btn {
      border: 3px solid currentColor;
      color: var(--green);
      background: #06100b;
      min-height: 36px;
      padding: 7px 12px;
      cursor: pointer;
      box-shadow: 4px 4px 0 #000;
      text-transform: uppercase;
      font-weight: 800;
    }

    .pixel-btn.blue { color: var(--blue); background: #06111d; }
    .pixel-btn.danger { color: var(--danger); background: #19070b; }
    .pixel-btn:active { transform: translate(2px, 2px); box-shadow: 2px 2px 0 #000; }
    .pixel-btn:disabled { opacity: .45; cursor: not-allowed; }

    .body {
      padding: 14px;
    }

    .stats-row {
      display: grid;
      grid-template-columns: 160px minmax(0, 1fr);
      gap: 14px;
      align-items: stretch;
    }

    .total-box {
      border: 3px solid var(--green2);
      background: #06100b;
      padding: 12px;
      display: grid;
      align-content: center;
      min-height: 132px;
    }

    .total-number {
      color: var(--green);
      font-size: 58px;
      line-height: .9;
      font-weight: 900;
    }

    .label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      margin-top: 8px;
    }

    .heatmap {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(13px, 1fr));
      gap: 5px;
      align-content: start;
      border: 3px solid #173a2b;
      padding: 10px;
      min-height: 132px;
      background: #020704;
    }

    .cell {
      aspect-ratio: 1 / 1;
      min-width: 10px;
      background: #102016;
      border: 1px solid #193421;
    }

    .cell.l1 { background: #155b37; }
    .cell.l2 { background: #1a9653; }
    .cell.l3 { background: #23cf72; }
    .cell.l4 { background: #77ffad; box-shadow: 0 0 8px rgba(57,255,136,.7); }

    .expanded-map {
      margin-top: 14px;
      grid-template-columns: repeat(auto-fill, minmax(10px, 1fr));
      display: none;
    }

    .apps.expanded .expanded-map { display: grid; }
    .apps.expanded .month-map { display: none; }

    .detail-strip {
      display: none;
      margin-top: 14px;
      gap: 10px;
      flex-wrap: wrap;
    }

    .apps.expanded .detail-strip { display: flex; }

    .mini-list {
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }

    .job-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      border: 2px solid #193421;
      background: #050b08;
      padding: 9px;
    }

    .job-main strong {
      color: var(--text);
      display: block;
      overflow-wrap: anywhere;
    }

    .job-main span {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }

    .status-pill {
      color: var(--blue);
      border: 2px solid var(--blue2);
      padding: 4px 7px;
      font-size: 12px;
      white-space: nowrap;
      background: #07111d;
    }

    .composer {
      display: grid;
      gap: 12px;
    }

    textarea {
      width: 100%;
      min-height: 230px;
      resize: vertical;
      color: var(--text);
      background: #030806;
      border: 3px solid var(--green2);
      padding: 12px;
      outline: none;
      box-shadow: inset 0 0 0 2px #020402;
    }

    textarea:focus, input:focus, select:focus {
      border-color: var(--green);
      box-shadow: 0 0 0 3px rgba(57,255,136,.16);
    }

    .settings {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }

    .field {
      display: grid;
      gap: 6px;
    }

    .field label {
      font-size: 11px;
      color: var(--muted);
      text-transform: uppercase;
    }

    input, select {
      min-width: 0;
      color: var(--text);
      background: #030806;
      border: 3px solid #184b34;
      min-height: 38px;
      padding: 6px 8px;
      outline: none;
    }

    .go-line {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }

    .terminal {
      margin-top: 12px;
      min-height: 120px;
      max-height: 260px;
      overflow: auto;
      white-space: pre-wrap;
      border: 3px solid #173a2b;
      background: #020402;
      color: #9effc5;
      padding: 10px;
      font-size: 12px;
    }

    .token-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }

    .token-box {
      border: 3px solid var(--blue2);
      background: #06111d;
      padding: 12px;
      min-width: 0;
    }

    .token-number {
      color: var(--blue);
      font-weight: 900;
      font-size: clamp(18px, 4vw, 28px);
      overflow-wrap: anywhere;
    }

    .token-bars {
      margin-top: 12px;
      display: grid;
      gap: 6px;
    }

    .bar {
      height: 16px;
      border: 2px solid #14385e;
      background: #050b12;
      position: relative;
      overflow: hidden;
    }

    .bar > i {
      display: block;
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, var(--blue2), var(--blue));
    }

    .overlay {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, .72);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 22px;
      z-index: 10;
    }

    .overlay.open { display: flex; }

    .modal {
      width: min(1180px, 100%);
      max-height: min(760px, calc(100vh - 44px));
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      border: var(--pixel) solid var(--blue);
      background: #050b12;
      box-shadow: 10px 10px 0 #000;
    }

    .modal-body {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(260px, .85fr) minmax(0, 1.15fr);
      gap: 0;
    }

    .jd-pane, .list-pane {
      min-height: 0;
      overflow: auto;
      padding: 12px;
    }

    .jd-pane {
      border-right: 4px solid var(--blue2);
      background: #03080d;
    }

    .jd-title {
      color: var(--green);
      font-weight: 900;
      margin-bottom: 8px;
      overflow-wrap: anywhere;
    }

    .jd-summary {
      color: var(--text);
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .modal-job {
      border: 3px solid #173a2b;
      padding: 10px;
      background: #06100b;
      margin-bottom: 10px;
      cursor: pointer;
      display: grid;
      gap: 8px;
    }

    .modal-job.active { border-color: var(--green); box-shadow: inset 0 0 0 2px #0b3f25; }
    .file-links { display: flex; gap: 8px; flex-wrap: wrap; }
    .file-links a {
      color: var(--blue);
      border: 2px solid var(--blue2);
      padding: 3px 6px;
      text-decoration: none;
      background: #04101c;
      font-size: 12px;
    }

    .side-only { grid-column: 2; }

    .archive-list {
      display: grid;
      gap: 10px;
      max-height: 260px;
      overflow: auto;
      margin-top: 12px;
    }

    .archive-row {
      border: 3px solid #14385e;
      background: #04101c;
      padding: 10px;
      display: grid;
      gap: 8px;
    }

    .archive-row strong {
      color: var(--blue);
      overflow-wrap: anywhere;
    }

    @media (max-width: 900px) {
      .grid, .modal-body, .stats-row, .settings { grid-template-columns: 1fr; }
      .side-only { grid-column: auto; }
      .topbar { align-items: flex-start; flex-direction: column; }
      .jd-pane { border-right: 0; border-bottom: 4px solid var(--blue2); max-height: 220px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <h1>CV Command Deck</h1>
        <span>Local CLI control surface / generated files stay in user_content/generated_cvs</span>
      </div>
      <div class="status-led"><span class="led"></span><span id="serverStatus">ONLINE</span></div>
    </header>

    <section class="grid">
      <div class="panel apps" id="appsPanel">
        <div class="panel-head">
          <div class="panel-title">Application Memory</div>
          <button class="pixel-btn" id="toggleApps">Expand</button>
        </div>
        <div class="body">
          <div class="stats-row">
            <div class="total-box">
              <div class="total-number" id="totalApps">0</div>
              <div class="label">Total applications</div>
            </div>
            <div class="heatmap month-map" id="monthMap"></div>
          </div>
          <div class="heatmap expanded-map" id="yearMap"></div>
          <div class="detail-strip">
            <button class="pixel-btn blue" id="openDetails">View Details</button>
            <span class="label" id="avgLine">Daily average pending</span>
          </div>
          <div class="mini-list" id="recentJobs"></div>
        </div>
      </div>

      <div class="panel blue">
        <div class="panel-head">
          <div class="panel-title">Token Dashboard</div>
          <button class="pixel-btn blue" id="refreshBtn">Refresh</button>
        </div>
        <div class="body">
          <div class="token-grid">
            <div class="token-box"><div class="token-number" id="inputTokens">0</div><div class="label">Input</div></div>
            <div class="token-box"><div class="token-number" id="outputTokens">0</div><div class="label">Output</div></div>
            <div class="token-box"><div class="token-number" id="totalTokens">0</div><div class="label">Total</div></div>
          </div>
          <div class="token-bars" id="tokenBars"></div>
        </div>
      </div>

      <div class="panel blue side-only">
        <div class="panel-head">
          <div class="panel-title">Drive Archive</div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="pixel-btn blue" id="archivePastBtn">2+ Days</button>
            <button class="pixel-btn blue" id="archiveBtn">Date Only</button>
          </div>
        </div>
        <div class="body">
          <div class="settings">
            <div class="field"><label>Date</label><input id="archiveDate" value="yesterday"></div>
            <div class="field"><label>Remote</label><input id="archiveRemote" placeholder="GDrive:CV Maker Archive"></div>
            <div class="field"><label>Mode</label><select id="archiveMode"><option value="delete">upload + delete local</option><option value="keep">upload + keep local</option><option value="dry">dry run</option></select></div>
          </div>
          <div class="archive-list" id="archiveList"></div>
        </div>
      </div>

      <div class="panel" style="grid-column: 1 / -1;">
        <div class="panel-head">
          <div class="panel-title">JD Chat Input</div>
          <button class="pixel-btn" id="goBtn">GO</button>
        </div>
        <div class="body composer">
          <textarea id="jdInput" placeholder="Paste a JD URL or raw job description text here..."></textarea>
          <div class="settings">
            <div class="field"><label>Provider</label><input id="providerInput" value="minimax"></div>
            <div class="field"><label>Model</label><input id="modelInput" value="MiniMax-M2.7"></div>
            <div class="field"><label>Format</label><select id="formatInput"><option value="latex">latex + pdf</option><option value="docx">docx</option></select></div>
            <div class="field"><label>Library</label><input id="libraryInput" value="user_content/library"></div>
            <div class="field"><label>Template</label><input id="templateInput" placeholder="optional docx template"></div>
            <div class="field"><label>Summarize years</label><input id="summarizeInput" value="10"></div>
          </div>
          <div class="go-line">
            <span class="label" id="runState">Idle</span>
            <button class="pixel-btn blue" id="clearLog">Clear Log</button>
          </div>
          <pre class="terminal" id="terminal">Ready.</pre>
        </div>
      </div>
    </section>
  </main>

  <div class="overlay" id="detailsOverlay">
    <div class="modal">
      <div class="panel-head">
        <div class="panel-title">Application Detail Matrix</div>
        <button class="pixel-btn danger" id="closeDetails">Close</button>
      </div>
      <div class="modal-body">
        <aside class="jd-pane">
          <div class="jd-title" id="detailTitle">Select a job</div>
          <div class="jd-summary" id="detailSummary"></div>
          <div class="file-links" id="detailFiles" style="margin-top: 12px;"></div>
        </aside>
        <section class="list-pane" id="detailList"></section>
      </div>
    </div>
  </div>

  <script>
    const state = { apps: [], statuses: [], archives: [], selectedId: null };
    const $ = (id) => document.getElementById(id);
    const fmt = (value) => new Intl.NumberFormat().format(value || 0);

    function fileHref(path) {
      return /^https?:\/\//.test(String(path || "")) ? path : `/files/${encodeURIComponent(path)}`;
    }

    function cellTitle(cell) {
      return `${cell.date}: ${cell.count} resume${cell.count === 1 ? "" : "s"}`;
    }

    function renderMap(target, cells) {
      target.innerHTML = "";
      cells.forEach(cell => {
        const node = document.createElement("span");
        node.className = `cell l${cell.level}`;
        node.title = cellTitle(cell);
        target.appendChild(node);
      });
    }

    function renderRecent() {
      $("recentJobs").innerHTML = "";
      state.apps.slice(0, 5).forEach(app => {
        const row = document.createElement("div");
        row.className = "job-row";
        row.innerHTML = `<div class="job-main"><strong>${escapeHtml(app.role)}</strong><span>${escapeHtml(app.company || "Unknown company")} / ${escapeHtml(app.date)}</span></div><span class="status-pill">${escapeHtml(app.status)}</span>`;
        $("recentJobs").appendChild(row);
      });
    }

    function renderTokens(tokens) {
      const totals = tokens.totals || {};
      $("inputTokens").textContent = fmt(totals.input);
      $("outputTokens").textContent = fmt(totals.output);
      $("totalTokens").textContent = fmt(totals.total);
      const daily = tokens.daily || {};
      const rows = Object.entries(daily).slice(-8);
      const max = Math.max(1, ...rows.map(([, v]) => v));
      $("tokenBars").innerHTML = "";
      rows.forEach(([date, value]) => {
        const wrap = document.createElement("div");
        wrap.innerHTML = `<div class="label">${date} / ${fmt(value)}</div><div class="bar"><i style="width:${Math.max(4, value / max * 100)}%"></i></div>`;
        $("tokenBars").appendChild(wrap);
      });
    }

    function renderArchives(archivesPayload) {
      const archives = (archivesPayload && archivesPayload.archives) || [];
      state.archives = archives;
      if (archivesPayload && archivesPayload.default_remote && !$("archiveRemote").value) {
        $("archiveRemote").value = archivesPayload.default_remote;
      }
      const target = $("archiveList");
      target.innerHTML = "";
      if (!archives.length) {
        target.innerHTML = `<div class="label">No Google Drive archive links saved yet.</div>`;
        return;
      }
      archives.slice(0, 6).forEach(archive => {
        const row = document.createElement("div");
        row.className = "archive-row";
        const files = archive.files || [];
        row.innerHTML = `
          <strong>${escapeHtml(archive.date)} / ${files.length} files</strong>
          <span class="label">${escapeHtml(archive.remote_dir || "")}</span>
          <div class="file-links">
            ${files.slice(0, 8).map(file => `<a href="${escapeHtml(file.download_link || "#")}" target="_blank">${escapeHtml(file.name)}</a>`).join("")}
          </div>
        `;
        target.appendChild(row);
      });
    }

    function renderDetails() {
      const list = $("detailList");
      list.innerHTML = "";
      if (!state.selectedId && state.apps[0]) state.selectedId = state.apps[0].id;
      const selected = state.apps.find(app => app.id === state.selectedId) || state.apps[0];

      if (selected) {
        $("detailTitle").textContent = `${selected.company ? selected.company + " / " : ""}${selected.role}`;
        $("detailSummary").textContent = selected.jd_summary || "No JD summary available.";
        $("detailFiles").innerHTML = "";
        Object.entries(selected.files || {}).forEach(([label, path]) => {
          const link = document.createElement("a");
          link.href = fileHref(path);
          link.textContent = label;
          link.target = "_blank";
          $("detailFiles").appendChild(link);
        });
        Object.entries(selected.archived_files || {}).forEach(([label, file]) => {
          if (!file.download_link) return;
          const link = document.createElement("a");
          link.href = file.download_link;
          link.textContent = `${label} drive`;
          link.target = "_blank";
          $("detailFiles").appendChild(link);
        });
      }

      state.apps.forEach(app => {
        const item = document.createElement("div");
        item.className = `modal-job ${app.id === state.selectedId ? "active" : ""}`;
        item.innerHTML = `
          <div class="job-main"><strong>${escapeHtml(app.role)}</strong><span>${escapeHtml(app.company || "Unknown company")} / ${escapeHtml(app.date)}</span></div>
          <select data-id="${escapeHtml(app.id)}">${state.statuses.map(s => `<option value="${s}" ${s === app.status ? "selected" : ""}>${s}</option>`).join("")}</select>
        `;
        item.addEventListener("click", (event) => {
          if (event.target.tagName === "SELECT") return;
          state.selectedId = app.id;
          renderDetails();
        });
        item.querySelector("select").addEventListener("change", async (event) => {
          await fetch(`/api/applications/${encodeURIComponent(app.id)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: event.target.value })
          });
          await loadDashboard();
          renderDetails();
        });
        list.appendChild(item);
      });
    }

    function escapeHtml(value) {
      return String(value || "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    async function loadDashboard() {
      const response = await fetch("/api/applications");
      const data = await response.json();
      state.apps = data.applications || [];
      state.statuses = data.statuses || [];
      $("totalApps").textContent = state.summary?.total || data.summary.total || state.apps.length;
      renderMap($("monthMap"), data.heatmap.month || []);
      renderMap($("yearMap"), data.heatmap.year || []);
      renderRecent();
      renderTokens(data.tokens || {});
      renderArchives(data.archives || {});
      const activeDays = new Set(state.apps.map(app => app.date)).size || 1;
      $("avgLine").textContent = `Daily average: ${(state.apps.length / activeDays).toFixed(2)} applications`;
    }

    async function runApply() {
      const jd = $("jdInput").value.trim();
      if (!jd) {
        $("terminal").textContent = "JD is required.";
        return;
      }
      $("goBtn").disabled = true;
      $("runState").textContent = "Running local run.py command...";
      $("terminal").textContent = "Executing. This can take a few minutes.\n";
      try {
        const response = await fetch("/api/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jd,
            provider: $("providerInput").value,
            model: $("modelInput").value,
            format: $("formatInput").value,
            library: $("libraryInput").value,
            template: $("templateInput").value,
            summarize: $("summarizeInput").value
          })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Generation failed.");
        $("terminal").textContent = data.log || "Done.";
        $("runState").textContent = "Done";
        await loadDashboard();
      } catch (error) {
        $("terminal").textContent += `\nERROR: ${error.message}`;
        $("runState").textContent = "Failed";
      } finally {
        $("goBtn").disabled = false;
      }
    }

    async function runArchive() {
      $("archiveBtn").disabled = true;
      $("runState").textContent = "Archiving selected date...";
      $("terminal").textContent = "Running archive command for the selected date only.\n";
      try {
        const mode = $("archiveMode").value;
        const response = await fetch("/api/archive", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            date: $("archiveDate").value,
            remote: $("archiveRemote").value,
            keep_local: mode === "keep",
            dry_run: mode === "dry"
          })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Selected date archive failed.");
        $("terminal").textContent = data.log || "Selected date archive complete.";
        $("runState").textContent = "Selected date archive complete";
        await loadDashboard();
      } catch (error) {
        $("terminal").textContent += `\nERROR: ${error.message}`;
        $("runState").textContent = "Selected date archive failed";
      } finally {
        $("archiveBtn").disabled = false;
      }
    }

    async function runArchivePast() {
      $("archivePastBtn").disabled = true;
      $("archiveBtn").disabled = true;
      $("runState").textContent = "Archiving files at least 2 days old...";
      $("terminal").textContent = "Uploading files dated two days ago or earlier to Google Drive, then deleting local copies after link capture.\n";
      try {
        const response = await fetch("/api/archive-old-files", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            remote: $("archiveRemote").value,
            min_age_days: 2
          })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Archive 2+ day files failed.");
        $("terminal").textContent = data.log || "Archive 2+ day files complete.";
        $("runState").textContent = "Archive 2+ day files complete";
        await loadDashboard();
      } catch (error) {
        $("terminal").textContent += `\nERROR: ${error.message}`;
        $("runState").textContent = "Archive 2+ day files failed";
      } finally {
        $("archivePastBtn").disabled = false;
        $("archiveBtn").disabled = false;
      }
    }

    $("toggleApps").addEventListener("click", () => {
      $("appsPanel").classList.toggle("expanded");
      $("toggleApps").textContent = $("appsPanel").classList.contains("expanded") ? "Shrink" : "Expand";
    });
    $("openDetails").addEventListener("click", () => {
      renderDetails();
      $("detailsOverlay").classList.add("open");
    });
    $("closeDetails").addEventListener("click", () => $("detailsOverlay").classList.remove("open"));
    $("refreshBtn").addEventListener("click", loadDashboard);
    $("goBtn").addEventListener("click", runApply);
    $("archiveBtn").addEventListener("click", runArchive);
    $("archivePastBtn").addEventListener("click", runArchivePast);
    $("clearLog").addEventListener("click", () => $("terminal").textContent = "Ready.");
    loadDashboard();
  </script>
</body>
</html>
"""


class CVWebHandler(BaseHTTPRequestHandler):
    server_version = "CVCommandDeck/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[web] {self.address_string()} - {fmt % args}\n")

    def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object.")
        return payload

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/applications":
            self._send_json(200, dashboard_payload())
            return
        if path == "/api/tokens":
            self._send_json(200, read_token_usage())
            return
        if path == "/api/archives":
            self._send_json(200, archive_payload())
            return
        if path.startswith("/files/"):
            self._serve_file(unquote(path[len("/files/"):]))
            return
        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        match = re.match(r"^/api/applications/([^/]+)$", parsed.path)
        if not match:
            self._send_json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json_body()
            record = update_application_status(unquote(match.group(1)), str(payload.get("status") or ""))
            self._send_json(200, {"application": record})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/apply":
            try:
                payload = self._read_json_body()
                result = run_application(payload)
                cli_log = (f"{result.stdout}\n{result.stderr}").strip()
                self._send_json(
                    200,
                    {
                        "application": result.record,
                        "log": (cli_log or "Done.")[-8000:],
                    },
                )
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if parsed.path == "/api/archive":
            try:
                payload = self._read_json_body()
                self._send_json(200, run_archive(payload))
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if parsed.path in {"/api/archive-old-files", "/api/archive-before-today"}:
            try:
                payload = self._read_json_body()
                self._send_json(200, run_archive_old_files(payload))
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        self._send_json(404, {"error": "Not found"})

    def _serve_file(self, relative_path: str) -> None:
        requested = (PROJECT_ROOT / relative_path).resolve()
        allowed_roots = [GENERATED_DIR.resolve(), INPUTS_DIR.resolve()]
        if not any(str(requested).startswith(str(root)) for root in allowed_roots):
            self._send_json(403, {"error": "Forbidden"})
            return
        if not requested.exists() or not requested.is_file():
            self._send_json(404, {"error": "File not found"})
            return

        content_types = {
            ".pdf": "application/pdf",
            ".tex": "text/plain; charset=utf-8",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain; charset=utf-8",
        }
        self._send(200, requested.read_bytes(), content_types.get(requested.suffix.lower(), "application/octet-stream"))


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    candidate = port
    while candidate < port + 20:
        try:
            httpd = ThreadingHTTPServer((host, candidate), CVWebHandler)
            print(f"CV Command Deck running at http://{host}:{candidate}")
            print("Press Ctrl+C to stop.")
            return httpd
        except OSError:
            candidate += 1
    raise OSError(f"No free port found from {port} to {candidate}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web UI for CV Maker")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    httpd = serve(args.host, args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping CV Command Deck.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
