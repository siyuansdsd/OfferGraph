"""Persistent local profile store for job application workflows."""

from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from config.env import PROJECT_ROOT, get_env


JOB_PROFILE_PATH_ENV = "OFFERGRAPH_JOB_PROFILE_PATH"
DEFAULT_JOB_PROFILE_PATH = PROJECT_ROOT / "local_data" / "job_application" / "profile.json"
UNCERTAIN_ANSWERS = {"", "?", "not sure", "unsure", "unknown", "不知道", "不确定"}
SKIP_ANSWERS = {
    "skip",
    "prefer not to answer",
    "prefer_not_to_answer",
    "不回答",
    "跳过",
}

DEFAULT_JOB_PROFILE: dict[str, Any] = {
    "profile": {
        "legal_name": "",
        "first_name": "",
        "last_name": "",
        "preferred_name": "",
        "email": "",
        "phone": "",
        "address": {
            "street": "",
            "city": "",
            "state": "",
            "postal_code": "",
            "country": "",
        },
        "linkedin_url": "",
        "github_url": "",
        "portfolio_url": "",
    },
    "work_authorization": {
        "country": "",
        "right_to_work": "",
        "requires_sponsorship": None,
        "visa_status": "",
        "security_clearance": "",
    },
    "answers": {
        "salary_expectation": "",
        "notice_period": "",
        "start_availability": "",
        "relocation": "",
        "work_arrangement": "",
        "diversity_questions_preference": "prefer_not_to_answer",
        "form_questions": {},
    },
    "question_history": [],
    "metadata": {
        "schema_version": 1,
        "description": "Local-only job application profile and reusable form answers.",
    },
}


class JobProfileReadInput(BaseModel):
    """Input schema for reading the local job application profile."""

    profile_path: str = Field(
        default="",
        description="Optional profile JSON path. Defaults to local_data/job_application/profile.json.",
    )
    create_if_missing: bool = Field(
        default=True,
        description="Create the profile file with defaults when it does not exist.",
    )


class JobProfileUpsertInput(BaseModel):
    """Input schema for updating the local job application profile."""

    updates: dict[str, Any] = Field(
        default_factory=dict,
        description="Profile updates. Dotted keys like profile.email are supported.",
    )
    profile_path: str = Field(default="", description="Optional profile JSON path.")


class JobProfileResolveQuestionsInput(BaseModel):
    """Input schema for resolving application form questions from profile data."""

    questions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Form blocker questions from an ATS page.",
    )
    profile_path: str = Field(default="", description="Optional profile JSON path.")
    interactive: bool = Field(
        default=True,
        description="When true, ask missing answers in the terminal if stdin is interactive.",
    )
    max_rounds: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum prompt rounds when answers remain incomplete.",
    )


def resolve_job_profile_path(profile_path: str | Path | None = None) -> Path:
    """Resolve the configured local job profile path."""
    configured = profile_path or get_env(JOB_PROFILE_PATH_ENV, "", load=True)
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DEFAULT_JOB_PROFILE_PATH


def read_job_profile(
    profile_path: str | Path | None = None,
    *,
    create_if_missing: bool = True,
) -> dict[str, Any]:
    """Read and normalize the job profile file."""
    path = resolve_job_profile_path(profile_path)
    if not path.exists():
        profile = copy.deepcopy(DEFAULT_JOB_PROFILE)
        if create_if_missing:
            save_job_profile(profile, path)
        return profile

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        loaded = {}
    profile = deep_merge(copy.deepcopy(DEFAULT_JOB_PROFILE), loaded if isinstance(loaded, dict) else {})
    if create_if_missing:
        save_job_profile(profile, path)
    return profile


def save_job_profile(profile: dict[str, Any], profile_path: str | Path | None = None) -> Path:
    """Persist the job profile JSON file."""
    path = resolve_job_profile_path(profile_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def upsert_job_profile(
    updates: dict[str, Any],
    profile_path: str | Path | None = None,
) -> dict[str, Any]:
    """Apply updates to the job profile and return the saved profile."""
    profile = read_job_profile(profile_path)
    for key, value in (updates or {}).items():
        if "." in key:
            set_dotted_value(profile, key, value)
        elif isinstance(value, dict) and isinstance(profile.get(key), dict):
            profile[key] = deep_merge(profile[key], value)
        else:
            profile[key] = value
    profile.setdefault("metadata", {})["updated_at"] = utc_timestamp()
    save_job_profile(profile, profile_path)
    return profile


def resolve_job_profile_questions(
    questions: list[dict[str, Any]],
    *,
    profile_path: str | Path | None = None,
    interactive: bool = True,
    max_rounds: int = 2,
    prompt_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Resolve application questions from profile data or terminal user input."""
    profile = read_job_profile(profile_path)
    normalized_questions = [normalize_question(question) for question in questions if question]
    resolved: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for question in normalized_questions:
        resolution = resolve_question_from_profile(question, profile)
        if resolution:
            resolved.append(resolution)
        else:
            missing.append(question)

    profile_updated = False
    can_prompt = bool(interactive and (sys.stdin.isatty() or prompt_func is not input))
    if missing and can_prompt:
        output_func("I need a few answers to continue this application:")
        for index, question in enumerate(missing, start=1):
            output_func(f"{index}. {format_question_for_prompt(question)}")

        remaining = missing
        for round_index in range(max_rounds):
            next_remaining: list[dict[str, Any]] = []
            for question in remaining:
                answer = prompt_func(f"{format_question_for_prompt(question)}: ").strip()
                parsed = normalize_user_answer(answer)
                if parsed is None:
                    next_remaining.append(question)
                    continue

                resolution = build_user_resolution(question, parsed)
                resolved.append(resolution)
                apply_resolution_to_profile(profile, resolution)
                profile_updated = True

            if not next_remaining:
                remaining = []
                break

            remaining = next_remaining
            if round_index < max_rounds - 1:
                output_func("These questions still need answers before I can continue:")
                for index, question in enumerate(remaining, start=1):
                    output_func(f"{index}. {format_question_for_prompt(question)}")

        missing = remaining

    if profile_updated:
        append_question_history(profile, resolved)
        profile.setdefault("metadata", {})["updated_at"] = utc_timestamp()
        save_job_profile(profile, profile_path)

    return {
        "status": "resolved" if not missing else "needs_input",
        "profile_path": str(resolve_job_profile_path(profile_path)),
        "profile_updated": profile_updated,
        "answers": resolved,
        "unresolved_questions": missing,
        "message": (
            "All form questions were resolved."
            if not missing
            else "Some form questions still need user input."
        ),
    }


def normalize_question(question: dict[str, Any]) -> dict[str, Any]:
    """Normalize one ATS blocker question."""
    label = compact_text(str(question.get("label") or question.get("question") or ""))
    name = compact_text(str(question.get("name") or question.get("id") or ""))
    field_type = compact_text(str(question.get("type") or question.get("tag") or "text"))
    options = question.get("options") or []
    if not isinstance(options, list):
        options = []
    normalized = {
        **question,
        "label": label,
        "name": name,
        "type": field_type,
        "options": [str(option) for option in options],
    }
    normalized["question_key"] = question_key(normalized)
    normalized["profile_path_hint"] = infer_profile_path(normalized)
    return normalized


def question_key(question: dict[str, Any]) -> str:
    """Build a stable key for a form question."""
    source = " ".join(
        str(question.get(part) or "")
        for part in ("name", "label", "type")
        if question.get(part)
    )
    return slugify(source, fallback="question")


def resolve_question_from_profile(
    question: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve a question from known profile values."""
    profile_path = question.get("profile_path_hint") or infer_profile_path(question)
    value = value_for_profile_path(profile, profile_path)
    if is_missing_value(value):
        stored = (
            profile.get("answers", {})
            .get("form_questions", {})
            .get(question.get("question_key") or question_key(question))
        )
        if isinstance(stored, dict):
            value = stored.get("answer")
            profile_path = stored.get("profile_path") or profile_path

    if is_missing_value(value):
        return None

    return build_resolution(
        question,
        answer=value,
        source="profile",
        profile_path=profile_path,
    )


def build_user_resolution(question: dict[str, Any], answer: Any) -> dict[str, Any]:
    """Build a user-supplied resolution record."""
    profile_path = question.get("profile_path_hint") or infer_profile_path(question)
    if not profile_path:
        profile_path = f"answers.form_questions.{question.get('question_key') or question_key(question)}.answer"
    return build_resolution(
        question,
        answer=answer,
        source="user",
        profile_path=profile_path,
    )


def build_resolution(
    question: dict[str, Any],
    *,
    answer: Any,
    source: str,
    profile_path: str,
) -> dict[str, Any]:
    """Return a normalized answer record."""
    normalized = normalize_question(question)
    return {
        "question": normalized,
        "question_key": normalized["question_key"],
        "label": normalized.get("label", ""),
        "name": normalized.get("name", ""),
        "type": normalized.get("type", ""),
        "answer": answer,
        "source": source,
        "profile_path": profile_path,
    }


def apply_resolution_to_profile(profile: dict[str, Any], resolution: dict[str, Any]) -> None:
    """Store a resolution in the profile file."""
    profile_path = str(resolution.get("profile_path") or "")
    answer = resolution.get("answer")
    if profile_path and not profile_path.startswith("answers.form_questions."):
        set_dotted_value(profile, profile_path, answer)

    question_key_value = str(resolution.get("question_key") or "")
    if question_key_value:
        form_questions = profile.setdefault("answers", {}).setdefault("form_questions", {})
        form_questions[question_key_value] = {
            "label": resolution.get("label", ""),
            "name": resolution.get("name", ""),
            "type": resolution.get("type", ""),
            "answer": answer,
            "profile_path": profile_path,
            "updated_at": utc_timestamp(),
        }


def append_question_history(profile: dict[str, Any], resolutions: list[dict[str, Any]]) -> None:
    """Append compact resolution history entries."""
    history = profile.setdefault("question_history", [])
    timestamp = utc_timestamp()
    for resolution in resolutions:
        if resolution.get("source") != "user":
            continue
        history.append(
            {
                "label": resolution.get("label", ""),
                "name": resolution.get("name", ""),
                "type": resolution.get("type", ""),
                "answer": resolution.get("answer"),
                "profile_path": resolution.get("profile_path", ""),
                "question_key": resolution.get("question_key", ""),
                "answered_at": timestamp,
            }
        )
    del history[:-200]


def infer_profile_path(question: dict[str, Any]) -> str:
    """Infer a profile dotted path from a form question label/name."""
    text = f"{question.get('label', '')} {question.get('name', '')}".lower()
    text = re.sub(r"[_-]+", " ", text)

    if "first name" in text or re.search(r"\bgiven name\b", text):
        return "profile.first_name"
    if "last name" in text or "surname" in text or "family name" in text:
        return "profile.last_name"
    if "legal name" in text or "full name" in text or re.search(r"\bname\b", text):
        return "profile.legal_name"
    if "email" in text:
        return "profile.email"
    if "phone" in text or "mobile" in text:
        return "profile.phone"
    if "linkedin" in text:
        return "profile.linkedin_url"
    if "github" in text:
        return "profile.github_url"
    if "portfolio" in text or "website" in text:
        return "profile.portfolio_url"
    if "postcode" in text or "postal" in text or "zip" in text:
        return "profile.address.postal_code"
    if "street" in text or "address line" in text or text.strip() == "address":
        return "profile.address.street"
    if "city" in text or "suburb" in text:
        return "profile.address.city"
    if "state" in text or "province" in text:
        return "profile.address.state"
    if "country" in text:
        return "profile.address.country"
    if "right to work" in text or "work authori" in text or "eligible to work" in text:
        return "work_authorization.right_to_work"
    if "sponsor" in text or "sponsorship" in text:
        return "work_authorization.requires_sponsorship"
    if "visa" in text:
        return "work_authorization.visa_status"
    if "security clearance" in text or "clearance" in text:
        return "work_authorization.security_clearance"
    if "salary" in text or "compensation" in text or "pay expectation" in text:
        return "answers.salary_expectation"
    if "notice" in text:
        return "answers.notice_period"
    if "start date" in text or "availability" in text:
        return "answers.start_availability"
    if "relocat" in text:
        return "answers.relocation"
    if "remote" in text or "hybrid" in text or "work arrangement" in text:
        return "answers.work_arrangement"
    if any(token in text for token in ("gender", "ethnicity", "disability", "veteran", "indigenous")):
        return "answers.diversity_questions_preference"
    return ""


def value_for_profile_path(profile: dict[str, Any], profile_path: str) -> Any:
    """Read a dotted path value, deriving first/last names when possible."""
    if profile_path == "profile.first_name":
        value = get_dotted_value(profile, profile_path)
        if value:
            return value
        legal_name = str(get_dotted_value(profile, "profile.legal_name") or "").strip()
        return legal_name.split()[0] if legal_name else ""
    if profile_path == "profile.last_name":
        value = get_dotted_value(profile, profile_path)
        if value:
            return value
        legal_name = str(get_dotted_value(profile, "profile.legal_name") or "").strip()
        parts = legal_name.split()
        return parts[-1] if len(parts) > 1 else ""
    return get_dotted_value(profile, profile_path)


def normalize_user_answer(answer: str) -> Any | None:
    """Normalize one terminal answer."""
    lowered = answer.strip().lower()
    if lowered in UNCERTAIN_ANSWERS:
        return None
    if lowered in SKIP_ANSWERS:
        return "prefer_not_to_answer"
    if lowered in {"yes", "y", "true", "是", "需要"}:
        return "Yes"
    if lowered in {"no", "n", "false", "否", "不需要"}:
        return "No"
    return answer.strip()


def format_question_for_prompt(question: dict[str, Any]) -> str:
    """Format a form question for terminal display."""
    label = str(question.get("label") or question.get("name") or question.get("question_key"))
    options = question.get("options") or []
    if options:
        return f"{label} Options: {', '.join(map(str, options[:8]))}"
    return label


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def get_dotted_value(data: dict[str, Any], path: str) -> Any:
    """Read a dotted path from nested dictionaries."""
    current: Any = data
    for part in [part for part in path.split(".") if part]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def set_dotted_value(data: dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted path on nested dictionaries."""
    parts = [part for part in path.split(".") if part]
    if not parts:
        return
    current = data
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def is_missing_value(value: Any) -> bool:
    """Return whether a profile value should be treated as missing."""
    return value is None or (isinstance(value, str) and not value.strip())


def compact_text(value: str) -> str:
    """Normalize whitespace."""
    return " ".join(str(value or "").split())


def slugify(value: str, *, fallback: str = "item") -> str:
    """Create a stable snake-ish key from text."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug[:120] or fallback


def utc_timestamp() -> str:
    """Return an ISO UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


@tool("job-profile-read", args_schema=JobProfileReadInput)
def job_profile_read(
    profile_path: str = "",
    create_if_missing: bool = True,
) -> dict[str, Any]:
    """Read the local job application profile JSON."""
    path = resolve_job_profile_path(profile_path or None)
    return {
        "status": "ready",
        "profile_path": str(path),
        "profile": read_job_profile(path, create_if_missing=create_if_missing),
    }


@tool("job-profile-upsert", args_schema=JobProfileUpsertInput)
def job_profile_upsert(
    updates: dict[str, Any],
    profile_path: str = "",
) -> dict[str, Any]:
    """Update the local job application profile JSON."""
    path = resolve_job_profile_path(profile_path or None)
    profile = upsert_job_profile(updates, path)
    return {
        "status": "ready",
        "profile_path": str(path),
        "profile": profile,
    }


@tool("job-profile-resolve-questions", args_schema=JobProfileResolveQuestionsInput)
def job_profile_resolve_questions(
    questions: list[dict[str, Any]],
    profile_path: str = "",
    interactive: bool = True,
    max_rounds: int = 2,
) -> dict[str, Any]:
    """Resolve ATS form questions from profile data or ask the user in the console."""
    return resolve_job_profile_questions(
        questions,
        profile_path=profile_path or None,
        interactive=interactive,
        max_rounds=max_rounds,
    )


__all__ = [
    "DEFAULT_JOB_PROFILE",
    "DEFAULT_JOB_PROFILE_PATH",
    "JOB_PROFILE_PATH_ENV",
    "apply_resolution_to_profile",
    "infer_profile_path",
    "job_profile_read",
    "job_profile_resolve_questions",
    "job_profile_upsert",
    "normalize_question",
    "question_key",
    "read_job_profile",
    "resolve_job_profile_path",
    "resolve_job_profile_questions",
    "save_job_profile",
    "upsert_job_profile",
]
