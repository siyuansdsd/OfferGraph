"""MCP server wrapper for the vendored AI CV Maker project."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from config.env import PROJECT_ROOT, get_env, load_project_env


DEFAULT_CV_MAKER_PROJECT_ROOT = PROJECT_ROOT / "external" / "cv_maker"
DEFAULT_CV_MAKER_USER_CONTENT_DIR = (
    PROJECT_ROOT / "local_data" / "cv_maker" / "user_content"
)
CV_MAKER_PROJECT_ROOT_ENV = "CV_MAKER_PROJECT_ROOT"
CV_MAKER_USER_CONTENT_DIR_ENV = "CV_MAKER_USER_CONTENT_DIR"
CV_MAKER_PYTHON_ENV = "CV_MAKER_PYTHON"
CV_MAKER_TIMEOUT_ENV = "CV_MAKER_TIMEOUT_SECONDS"
CV_TAILORING_MCP_HOST_ENV = "CV_TAILORING_MCP_HOST"
CV_TAILORING_MCP_PORT_ENV = "CV_TAILORING_MCP_PORT"
CV_TAILORING_MCP_PATH_ENV = "CV_TAILORING_MCP_PATH"
CV_TAILORING_MCP_TRANSPORT_ENV = "CV_TAILORING_MCP_TRANSPORT"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_CV_TAILORING_MCP_HOST = "127.0.0.1"
DEFAULT_CV_TAILORING_MCP_PORT = 8765
DEFAULT_CV_TAILORING_MCP_PATH = "/mcp"
DEFAULT_CV_TAILORING_MCP_TRANSPORT = "streamable-http"
MCPTransport = Literal["stdio", "sse", "streamable-http"]
SUPPORTED_PROVIDERS = ("auto", "gemini", "vertex", "openai", "minimax", "anthropic", "github")
SUPPORTED_OUTPUT_FORMATS = ("docx", "latex")


class CommandResult(BaseModel):
    """Structured subprocess result for CV Maker commands."""

    exit_code: int
    command: list[str]
    stdout: str
    stderr: str


class TailorCVResult(BaseModel):
    """Result returned by the cv_tailor_resume MCP tool."""

    status: Literal["ready", "error"]
    message: str
    project_root: str
    command: list[str]
    exit_code: int
    generated_files: list[str] = Field(default_factory=list)
    jd_input_path: str | None = None
    stdout: str = ""
    stderr: str = ""


mcp = FastMCP(
    "offergraph-cv-tailoring",
    instructions=(
        "Wrap the vendored AI CV Maker project as reusable MCP tools. "
        "Use this server to tailor resumes and cover letters for a job description. "
        "Never submit job applications; return generated file paths for user review."
    ),
    host=get_env(CV_TAILORING_MCP_HOST_ENV, DEFAULT_CV_TAILORING_MCP_HOST)
    or DEFAULT_CV_TAILORING_MCP_HOST,
    port=int(
        get_env(CV_TAILORING_MCP_PORT_ENV, str(DEFAULT_CV_TAILORING_MCP_PORT))
        or DEFAULT_CV_TAILORING_MCP_PORT
    ),
    streamable_http_path=(
        get_env(CV_TAILORING_MCP_PATH_ENV, DEFAULT_CV_TAILORING_MCP_PATH)
        or DEFAULT_CV_TAILORING_MCP_PATH
    ),
)


@mcp.tool()
def cv_tailoring_health() -> dict[str, Any]:
    """Check whether the CV Maker project can be called."""
    try:
        project_root = resolve_cv_maker_project_root()
        python_executable = resolve_cv_maker_python(project_root)
        run_py = project_root / "run.py"
        src_dir = project_root / "src" / "cv_maker"
        return {
            "status": "ready",
            "project_root": str(project_root),
            "python": str(python_executable),
            "run_py": str(run_py),
            "src": str(src_dir),
            "message": "CV Maker project is available.",
        }
    except RuntimeError as exc:
        return {
            "status": "error",
            "message": str(exc),
        }


@mcp.tool()
def cv_tailoring_list_models(
    provider: str = "auto",
    model: str = "",
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """List models available to the CV Maker project."""
    try:
        project_root = resolve_cv_maker_project_root()
        command = build_list_models_command(
            project_root,
            provider=provider,
            model=model or None,
        )
        result = run_cv_maker_command(
            command,
            project_root=project_root,
            timeout_seconds=resolve_timeout(timeout_seconds),
        )
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "error",
            "message": str(exc),
        }

    return {
        "status": "ready" if result.exit_code == 0 else "error",
        "message": "Model listing finished." if result.exit_code == 0 else "Model listing failed.",
        **result.model_dump(),
    }


@mcp.tool()
def cv_tailor_resume(
    job_description: str = "",
    job_description_path: str = "",
    job_url: str = "",
    library: str = "user_content/library",
    template: str = "",
    output: str = "Tailored_CV.docx",
    output_format: str = "docx",
    provider: str = "auto",
    model: str = "",
    github: str = "",
    suggestions: str = "",
    summarize_years: int = 10,
    no_compile: bool = False,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """Tailor a CV and cover letter for a job description.

    Provide exactly one of job_description, job_description_path, or job_url.
    The CV Maker project writes generated documents into its own
    user_content/generated_cvs directory unless output points elsewhere.
    """
    try:
        project_root = resolve_cv_maker_project_root()
        jd_reference, created_jd_path = prepare_job_description_input(
            project_root,
            job_description=job_description,
            job_description_path=job_description_path,
            job_url=job_url,
        )
        generated_dir = project_root / "user_content" / "generated_cvs"
        before_snapshot = snapshot_generated_files(generated_dir)
        command = build_tailor_command(
            project_root,
            jd_reference=jd_reference,
            library=library,
            template=template or None,
            output=output,
            output_format=output_format,
            provider=provider,
            model=model or None,
            github=github or None,
            suggestions=suggestions or None,
            summarize_years=summarize_years,
            no_compile=no_compile,
        )
        result = run_cv_maker_command(
            command,
            project_root=project_root,
            timeout_seconds=resolve_timeout(timeout_seconds),
        )
        generated_files = changed_generated_files(generated_dir, before_snapshot)
    except (RuntimeError, ValueError) as exc:
        return TailorCVResult(
            status="error",
            message=str(exc),
            project_root=str(get_configured_project_root()),
            command=[],
            exit_code=1,
        ).model_dump(exclude_none=True)

    status = "ready" if result.exit_code == 0 else "error"
    message = (
        "Tailored CV workflow finished."
        if result.exit_code == 0
        else "Tailored CV workflow failed."
    )
    return TailorCVResult(
        status=status,
        message=message,
        project_root=str(project_root),
        command=result.command,
        exit_code=result.exit_code,
        generated_files=[str(path) for path in generated_files],
        jd_input_path=str(created_jd_path) if created_jd_path else None,
        stdout=result.stdout,
        stderr=result.stderr,
    ).model_dump(exclude_none=True)


def get_configured_project_root() -> Path:
    """Return the configured CV Maker project root without validating it."""
    load_project_env()
    return resolve_project_relative_path(
        get_env(
            CV_MAKER_PROJECT_ROOT_ENV,
            str(DEFAULT_CV_MAKER_PROJECT_ROOT),
            load=False,
        )
        or DEFAULT_CV_MAKER_PROJECT_ROOT
    ).expanduser()


def get_configured_user_content_dir() -> Path:
    """Return the configured ignored user_content directory."""
    load_project_env()
    return resolve_project_relative_path(
        get_env(
            CV_MAKER_USER_CONTENT_DIR_ENV,
            str(DEFAULT_CV_MAKER_USER_CONTENT_DIR),
            load=False,
        )
        or DEFAULT_CV_MAKER_USER_CONTENT_DIR
    )


def resolve_project_relative_path(path: str | Path) -> Path:
    """Resolve relative config paths from the OfferGraph project root."""
    resolved_path = Path(path).expanduser()
    if resolved_path.is_absolute():
        return resolved_path
    return PROJECT_ROOT / resolved_path


def resolve_cv_maker_project_root() -> Path:
    """Resolve and validate the external CV Maker project root."""
    project_root = get_configured_project_root().resolve()
    run_py = project_root / "run.py"
    src_dir = project_root / "src" / "cv_maker"
    if not run_py.exists():
        raise RuntimeError(f"CV Maker run.py not found: {run_py}")
    if not src_dir.exists():
        raise RuntimeError(f"CV Maker src/cv_maker directory not found: {src_dir}")
    ensure_cv_maker_user_content(project_root)
    return project_root


def ensure_cv_maker_user_content(project_root: Path) -> Path:
    """Ensure vendored CV Maker uses ignored local user_content data."""
    user_content_dir = get_configured_user_content_dir().resolve()
    user_content_dir.mkdir(parents=True, exist_ok=True)

    link_path = project_root / "user_content"
    if not _should_manage_user_content_link(project_root):
        return link_path

    if link_path.is_symlink():
        if link_path.resolve() != user_content_dir:
            link_path.unlink()
            link_path.symlink_to(user_content_dir, target_is_directory=True)
        return link_path

    if link_path.exists():
        raise RuntimeError(
            f"CV Maker user_content path already exists and is not a symlink: {link_path}. "
            f"Move private data to {user_content_dir} and replace it with a symlink."
        )

    link_path.symlink_to(user_content_dir, target_is_directory=True)
    return link_path


def _should_manage_user_content_link(project_root: Path) -> bool:
    return project_root.resolve() == DEFAULT_CV_MAKER_PROJECT_ROOT.resolve()


def resolve_cv_maker_python(project_root: Path) -> Path:
    """Resolve the Python executable used to run CV Maker."""
    configured_python = get_env(CV_MAKER_PYTHON_ENV, load=True)
    if configured_python:
        python_path = Path(configured_python).expanduser()
        if not python_path.exists():
            raise RuntimeError(f"Configured CV Maker Python not found: {python_path}")
        return python_path

    project_venv_python = project_root / ".venv" / "bin" / "python"
    if project_venv_python.exists():
        return project_venv_python

    return Path(sys.executable)


def resolve_timeout(timeout_seconds: int | None) -> int:
    """Resolve command timeout from tool input or environment."""
    if timeout_seconds is not None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        return timeout_seconds

    configured_timeout = get_env(CV_MAKER_TIMEOUT_ENV, str(DEFAULT_TIMEOUT_SECONDS), load=True)
    try:
        value = int(configured_timeout or DEFAULT_TIMEOUT_SECONDS)
    except ValueError:
        raise ValueError(f"{CV_MAKER_TIMEOUT_ENV} must be an integer.") from None
    if value <= 0:
        raise ValueError(f"{CV_MAKER_TIMEOUT_ENV} must be positive.")
    return value


def prepare_job_description_input(
    project_root: Path,
    *,
    job_description: str,
    job_description_path: str,
    job_url: str,
) -> tuple[str, Path | None]:
    """Return the JD reference for CV Maker, writing raw JD text when needed."""
    provided = [
        bool(job_description.strip()),
        bool(job_description_path.strip()),
        bool(job_url.strip()),
    ]
    if sum(provided) != 1:
        raise ValueError(
            "Provide exactly one of job_description, job_description_path, or job_url."
        )

    if job_url.strip():
        return job_url.strip(), None

    if job_description_path.strip():
        return job_description_path.strip(), None

    inputs_dir = project_root / "user_content" / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    filename = f"offergraph_mcp_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.txt"
    jd_path = inputs_dir / filename
    jd_path.write_text(job_description.strip() + "\n", encoding="utf-8")
    return str(jd_path), jd_path


def build_list_models_command(
    project_root: Path,
    *,
    provider: str,
    model: str | None = None,
) -> list[str]:
    """Build a CV Maker --list-models command."""
    validate_provider(provider)
    command = [
        str(resolve_cv_maker_python(project_root)),
        "run.py",
        "--list-models",
        "--provider",
        provider,
    ]
    if model:
        command.extend(["--model", model])
    return command


def build_tailor_command(
    project_root: Path,
    *,
    jd_reference: str,
    library: str,
    template: str | None,
    output: str,
    output_format: str,
    provider: str,
    model: str | None,
    github: str | None,
    suggestions: str | None,
    summarize_years: int,
    no_compile: bool,
) -> list[str]:
    """Build a CV Maker tailoring command."""
    validate_provider(provider)
    validate_output_format(output_format)
    if summarize_years < 0:
        raise ValueError("summarize_years must be zero or positive.")

    command = [
        str(resolve_cv_maker_python(project_root)),
        "run.py",
        "--jd",
        jd_reference,
        "--library",
        library,
        "--output",
        output,
        "--format",
        output_format,
        "--provider",
        provider,
        "--summarize",
        str(summarize_years),
        "--quiet",
    ]
    if template:
        command.extend(["--template", template])
    if model:
        command.extend(["--model", model])
    if github:
        command.extend(["--github", github])
    if suggestions:
        command.extend(["--suggestions", suggestions])
    if no_compile:
        command.append("--no-compile")
    return command


def run_cv_maker_command(
    command: list[str],
    *,
    project_root: Path,
    timeout_seconds: int,
) -> CommandResult:
    """Run a CV Maker command and capture output."""
    completed = subprocess.run(
        command,
        cwd=str(project_root),
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return CommandResult(
        exit_code=completed.returncode,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def snapshot_generated_files(generated_dir: Path) -> dict[Path, tuple[int, int]]:
    """Snapshot generated CV files by mtime and size."""
    if not generated_dir.exists():
        return {}
    return {
        path: (path.stat().st_mtime_ns, path.stat().st_size)
        for path in generated_dir.iterdir()
        if path.is_file()
    }


def changed_generated_files(
    generated_dir: Path,
    before_snapshot: dict[Path, tuple[int, int]],
) -> list[Path]:
    """Return files created or modified since the previous snapshot."""
    if not generated_dir.exists():
        return []

    changed: list[Path] = []
    for path in generated_dir.iterdir():
        if not path.is_file():
            continue
        current = (path.stat().st_mtime_ns, path.stat().st_size)
        if before_snapshot.get(path) != current:
            changed.append(path.resolve())

    return sorted(changed, key=lambda path: path.name)


def validate_provider(provider: str) -> None:
    """Validate CV Maker provider input."""
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"provider must be one of: {', '.join(SUPPORTED_PROVIDERS)}"
        )


def validate_output_format(output_format: str) -> None:
    """Validate CV Maker output format input."""
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(
            f"output_format must be one of: {', '.join(SUPPORTED_OUTPUT_FORMATS)}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CV Tailoring MCP server arguments."""
    parser = argparse.ArgumentParser(description="Run the CV Tailoring MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default=get_env(
            CV_TAILORING_MCP_TRANSPORT_ENV,
            DEFAULT_CV_TAILORING_MCP_TRANSPORT,
        )
        or DEFAULT_CV_TAILORING_MCP_TRANSPORT,
        help="MCP transport. Use streamable-http for a separately running service.",
    )
    parser.add_argument(
        "--host",
        default=mcp.settings.host,
        help="HTTP host for streamable-http or SSE transport.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=mcp.settings.port,
        help="HTTP port for streamable-http or SSE transport.",
    )
    parser.add_argument(
        "--path",
        default=mcp.settings.streamable_http_path,
        help="HTTP path for streamable-http transport.",
    )
    return parser.parse_args(argv)


def configure_http_server(host: str, port: int, path: str) -> None:
    """Configure FastMCP HTTP settings before running the server."""
    if port <= 0:
        raise ValueError("MCP server port must be positive.")
    if not path.startswith("/"):
        raise ValueError("MCP server path must start with '/'.")

    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.streamable_http_path = path


def main(argv: list[str] | None = None) -> None:
    """Run the CV Tailoring MCP service."""
    args = parse_args(argv)
    if args.transport == "streamable-http":
        configure_http_server(args.host, args.port, args.path)
    elif args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    try:
        mcp.run(transport=args.transport)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
