"""Project environment loading helpers."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def load_project_env(
    env_file: str | Path | None = None,
    *,
    override: bool = False,
) -> bool:
    """Load environment variables from the project `.env` file."""
    path = Path(env_file).expanduser() if env_file else DEFAULT_ENV_FILE
    return load_dotenv(path, override=override)


def get_env(
    name: str,
    default: str | None = None,
    *,
    load: bool = True,
) -> str | None:
    """Read an environment variable after loading project defaults."""
    if load:
        load_project_env()
    return os.getenv(name, default)


def require_env(name: str, *, load: bool = True) -> str:
    """Read a required environment variable or raise a clear error."""
    value = get_env(name, load=load)
    if value:
        return value
    raise RuntimeError(f"Missing required environment variable: {name}")


__all__ = [
    "DEFAULT_ENV_FILE",
    "PROJECT_ROOT",
    "get_env",
    "load_project_env",
    "require_env",
]
