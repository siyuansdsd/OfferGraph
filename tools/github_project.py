"""GitHub project inspection tools for content workflows."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolArg, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field

from config.env import get_env, load_project_env
from tools.research_tools import get_today_str, unique_filename
from tools.state import PlanMasterState


GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
DEFAULT_GITHUB_RECENT_ITEM_LIMIT = 5
GITHUB_REPO_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com[:/]"
    r"(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GitHubRepoReference:
    """A parsed GitHub repository reference."""

    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        """Return owner/repo."""
        return f"{self.owner}/{self.repo}"


class GitHubProjectReport(BaseModel):
    """Normalized GitHub project inspection result."""

    status: str = "ok"
    repository: dict[str, Any]
    recent_pull_requests: list[dict[str, Any]] = Field(default_factory=list)
    recent_issues: list[dict[str, Any]] = Field(default_factory=list)
    recent_commits: list[dict[str, Any]] = Field(default_factory=list)
    recent_releases: list[dict[str, Any]] = Field(default_factory=list)
    readme_excerpt: str | None = None


def parse_github_repo_reference(reference: str) -> GitHubRepoReference:
    """Parse a GitHub URL, git remote, or owner/repo string."""
    value = reference.strip()
    if not value:
        raise ValueError("GitHub project reference is required.")

    extracted = extract_github_repo_references(value)
    if extracted:
        return extracted[0]

    if value.startswith("git@github.com:"):
        value = value.removeprefix("git@github.com:")

    parts = value.split("/")
    if len(parts) < 2:
        raise ValueError(
            "GitHub project reference must be a GitHub URL or owner/repo string."
        )

    owner = parts[0].strip()
    repo = _clean_repo_name(parts[1].strip())
    if not owner or not repo:
        raise ValueError(
            "GitHub project reference must include both owner and repository."
        )
    return GitHubRepoReference(owner=owner, repo=repo)


def extract_github_repo_references(text: str) -> list[GitHubRepoReference]:
    """Extract GitHub repository references from arbitrary text."""
    references: list[GitHubRepoReference] = []
    seen: set[str] = set()

    for match in GITHUB_REPO_PATTERN.finditer(text):
        owner = match.group("owner")
        repo = _clean_repo_name(match.group("repo"))
        if not owner or not repo:
            continue
        reference = GitHubRepoReference(owner=owner, repo=repo)
        if reference.full_name not in seen:
            references.append(reference)
            seen.add(reference.full_name)

    if references:
        return references

    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.netloc.lower() in {"github.com", "www.github.com"}:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            reference = GitHubRepoReference(
                owner=parts[0],
                repo=_clean_repo_name(parts[1]),
            )
            return [reference]

    return references


def inspect_github_project(
    project: str,
    *,
    include_readme: bool = True,
    recent_item_limit: int = DEFAULT_GITHUB_RECENT_ITEM_LIMIT,
    client: httpx.Client | None = None,
) -> GitHubProjectReport:
    """Fetch GitHub project metadata and recent activity."""
    reference = parse_github_repo_reference(project)
    owns_client = client is None
    active_client = client or httpx.Client(timeout=30.0)
    headers = build_github_headers()
    try:
        repo_data = fetch_github_json(
            active_client,
            f"/repos/{reference.owner}/{reference.repo}",
            headers=headers,
        )
        pulls = fetch_github_json(
            active_client,
            f"/repos/{reference.owner}/{reference.repo}/pulls",
            headers=headers,
            params={
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": recent_item_limit,
            },
        )
        issues = fetch_github_json(
            active_client,
            f"/repos/{reference.owner}/{reference.repo}/issues",
            headers=headers,
            params={
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": recent_item_limit * 2,
            },
        )
        commits = fetch_github_json(
            active_client,
            f"/repos/{reference.owner}/{reference.repo}/commits",
            headers=headers,
            params={"per_page": recent_item_limit},
        )
        releases = fetch_github_json(
            active_client,
            f"/repos/{reference.owner}/{reference.repo}/releases",
            headers=headers,
            params={"per_page": min(recent_item_limit, 3)},
        )
        readme_excerpt = (
            fetch_github_readme_excerpt(
                active_client,
                reference,
                headers=headers,
            )
            if include_readme
            else None
        )
    finally:
        if owns_client:
            active_client.close()

    return GitHubProjectReport(
        repository=normalize_repository(repo_data),
        recent_pull_requests=[normalize_pull_request(item) for item in pulls],
        recent_issues=[
            normalize_issue(item)
            for item in issues
            if "pull_request" not in item
        ][:recent_item_limit],
        recent_commits=[normalize_commit(item) for item in commits],
        recent_releases=[normalize_release(item) for item in releases],
        readme_excerpt=readme_excerpt,
    )


def fetch_github_json(
    client: httpx.Client,
    path: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> Any:
    """Fetch JSON from the GitHub REST API."""
    response = client.get(
        f"{GITHUB_API_BASE_URL}{path}",
        headers=headers,
        params=params,
    )
    response.raise_for_status()
    return response.json()


def fetch_github_readme_excerpt(
    client: httpx.Client,
    reference: GitHubRepoReference,
    *,
    headers: dict[str, str],
    max_chars: int = 1200,
) -> str | None:
    """Fetch and decode a README excerpt, returning None when absent."""
    try:
        readme_data = fetch_github_json(
            client,
            f"/repos/{reference.owner}/{reference.repo}/readme",
            headers=headers,
        )
    except httpx.HTTPStatusError:
        return None

    content = str(readme_data.get("content") or "")
    if not content:
        return None
    try:
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return None
    return " ".join(decoded.split())[:max_chars]


def build_github_headers() -> dict[str, str]:
    """Build GitHub API headers, using GITHUB_TOKEN when available."""
    load_project_env()
    token = get_env(GITHUB_TOKEN_ENV, load=False)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "OfferGraph GitHub project inspector",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


@tool("github-project-inspector", parse_docstring=True)
def github_project_inspector(
    project: str,
    state: Annotated[PlanMasterState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    include_readme: bool = True,
    recent_item_limit: Annotated[int, InjectedToolArg] = DEFAULT_GITHUB_RECENT_ITEM_LIMIT,
) -> Command:
    """Inspect a GitHub project and save repo progress data to files.

    Args:
        project: GitHub URL, git remote URL, owner/repo, or text containing a GitHub URL.
        state: Injected agent state for virtual file storage.
        tool_call_id: Injected tool call identifier.
        include_readme: Whether to fetch and summarize the README.
        recent_item_limit: Number of recent PRs, issues, commits, and releases to fetch.
    """
    files = dict(state.get("files", {}))
    try:
        report = inspect_github_project(
            project,
            include_readme=include_readme,
            recent_item_limit=recent_item_limit,
        )
    except (httpx.HTTPError, ValueError) as exc:
        message = f"GitHub project inspection failed: {exc}"
        return Command(
            update={
                "files": files,
                "messages": [ToolMessage(message, tool_call_id=tool_call_id)],
            }
        )

    repository = report.repository
    filename = unique_filename(
        f"github_project_{repository['full_name'].replace('/', '_')}.md"
    )
    files[filename] = format_github_project_report(report)
    summary = summarize_github_project_report(report, filename=filename)

    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(summary, tool_call_id=tool_call_id)],
        }
    )


def normalize_repository(repo_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize GitHub repository metadata."""
    return {
        "full_name": repo_data.get("full_name"),
        "html_url": repo_data.get("html_url"),
        "description": repo_data.get("description"),
        "stars": repo_data.get("stargazers_count", 0),
        "forks": repo_data.get("forks_count", 0),
        "watchers": repo_data.get("watchers_count", 0),
        "open_issues": repo_data.get("open_issues_count", 0),
        "language": repo_data.get("language"),
        "topics": repo_data.get("topics", []),
        "default_branch": repo_data.get("default_branch"),
        "license": (repo_data.get("license") or {}).get("spdx_id"),
        "created_at": repo_data.get("created_at"),
        "updated_at": repo_data.get("updated_at"),
        "pushed_at": repo_data.get("pushed_at"),
        "archived": repo_data.get("archived", False),
        "visibility": repo_data.get("visibility"),
    }


def normalize_pull_request(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a GitHub pull request item."""
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "html_url": item.get("html_url"),
        "author": (item.get("user") or {}).get("login"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "merged_at": item.get("merged_at"),
    }


def normalize_issue(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a GitHub issue item."""
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "html_url": item.get("html_url"),
        "author": (item.get("user") or {}).get("login"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def normalize_commit(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a GitHub commit item."""
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    return {
        "sha": str(item.get("sha") or "")[:7],
        "html_url": item.get("html_url"),
        "message": str(commit.get("message") or "").splitlines()[0],
        "author": author.get("name"),
        "date": author.get("date"),
    }


def normalize_release(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a GitHub release item."""
    return {
        "name": item.get("name") or item.get("tag_name"),
        "tag_name": item.get("tag_name"),
        "html_url": item.get("html_url"),
        "published_at": item.get("published_at"),
        "prerelease": item.get("prerelease", False),
    }


def summarize_github_project_report(
    report: GitHubProjectReport,
    *,
    filename: str,
) -> str:
    """Build a compact tool result summary."""
    repo = report.repository
    return (
        f"Inspected GitHub project {repo['full_name']}: "
        f"{repo['stars']} stars, {repo['forks']} forks, "
        f"{repo['open_issues']} open issues, last push {repo.get('pushed_at')}. "
        f"Recent activity: {len(report.recent_pull_requests)} PR(s), "
        f"{len(report.recent_issues)} issue(s), "
        f"{len(report.recent_commits)} commit(s), "
        f"{len(report.recent_releases)} release(s). "
        f"Saved details to {filename}. Use read_file() before citing exact metrics."
    )


def format_github_project_report(report: GitHubProjectReport) -> str:
    """Format a GitHub project report as markdown for virtual file storage."""
    repo = report.repository
    lines = [
        f"# GitHub Project: {repo['full_name']}",
        "",
        f"**URL:** {repo.get('html_url')}",
        f"**Date:** {get_today_str()}",
        "",
        "## Repository Metrics",
        f"- Description: {repo.get('description') or 'None'}",
        f"- Stars: {repo.get('stars')}",
        f"- Forks: {repo.get('forks')}",
        f"- Watchers: {repo.get('watchers')}",
        f"- Open issues: {repo.get('open_issues')}",
        f"- Language: {repo.get('language') or 'Unknown'}",
        f"- Topics: {', '.join(repo.get('topics') or []) or 'None'}",
        f"- Default branch: {repo.get('default_branch') or 'Unknown'}",
        f"- License: {repo.get('license') or 'Unknown'}",
        f"- Last push: {repo.get('pushed_at') or 'Unknown'}",
        f"- Last update: {repo.get('updated_at') or 'Unknown'}",
        "",
        "## Recent Pull Requests",
        *_format_items(report.recent_pull_requests),
        "",
        "## Recent Issues",
        *_format_items(report.recent_issues),
        "",
        "## Recent Commits",
        *_format_items(report.recent_commits),
        "",
        "## Recent Releases",
        *_format_items(report.recent_releases),
    ]

    if report.readme_excerpt:
        lines.extend(["", "## README Excerpt", report.readme_excerpt])

    return "\n".join(lines)


def _format_items(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- None"]
    formatted: list[str] = []
    for item in items:
        title = item.get("title") or item.get("message") or item.get("name") or "Untitled"
        url = item.get("html_url")
        meta = item.get("state") or item.get("date") or item.get("published_at") or ""
        if item.get("number"):
            title = f"#{item['number']} {title}"
        formatted.append(f"- {title} ({meta}) {url or ''}".strip())
    return formatted


def _clean_repo_name(repo: str) -> str:
    return repo.removesuffix(".git").strip().strip(".,)")


__all__ = [
    "DEFAULT_GITHUB_RECENT_ITEM_LIMIT",
    "GITHUB_TOKEN_ENV",
    "GitHubProjectReport",
    "GitHubRepoReference",
    "build_github_headers",
    "extract_github_repo_references",
    "fetch_github_json",
    "format_github_project_report",
    "github_project_inspector",
    "inspect_github_project",
    "parse_github_repo_reference",
    "summarize_github_project_report",
]
