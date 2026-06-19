"""Tests for GitHub project inspection tools."""

import base64
from unittest import TestCase
from unittest.mock import patch

import httpx

from tools.github_project import (
    GITHUB_API_BASE_URL,
    GITHUB_TOKEN_ENV,
    build_github_headers,
    extract_github_repo_references,
    github_project_inspector,
    inspect_github_project,
    parse_github_repo_reference,
)


class FakeGitHubResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.request = httpx.Request("GET", "https://api.github.com/test")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "GitHub API error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self):
        return self.payload


class FakeGitHubClient:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.calls = []
        self.closed = False

    def get(self, url: str, headers=None, params=None):
        self.calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        path = url.removeprefix(GITHUB_API_BASE_URL)
        payload = self.routes.get(path)
        if payload is None:
            return FakeGitHubResponse({"message": "Not found"}, status_code=404)
        return FakeGitHubResponse(payload)

    def close(self) -> None:
        self.closed = True


class GitHubProjectToolsTest(TestCase):
    def test_parse_github_repo_reference_accepts_common_forms(self) -> None:
        self.assertEqual(
            parse_github_repo_reference("siyuansdsd/OfferGraph").full_name,
            "siyuansdsd/OfferGraph",
        )
        self.assertEqual(
            parse_github_repo_reference(
                "https://github.com/siyuansdsd/OfferGraph/pulls"
            ).full_name,
            "siyuansdsd/OfferGraph",
        )
        self.assertEqual(
            parse_github_repo_reference(
                "git@github.com:siyuansdsd/OfferGraph.git"
            ).full_name,
            "siyuansdsd/OfferGraph",
        )

    def test_extract_github_repo_references_from_text(self) -> None:
        references = extract_github_repo_references(
            "Review https://github.com/siyuansdsd/OfferGraph and "
            "https://github.com/jhcook/cv."
        )

        self.assertEqual(
            [reference.full_name for reference in references],
            ["siyuansdsd/OfferGraph", "jhcook/cv"],
        )

    def test_build_github_headers_uses_token_when_available(self) -> None:
        with patch("tools.github_project.load_project_env", return_value=True), patch(
            "tools.github_project.get_env",
            return_value="ghp_test",
        ):
            headers = build_github_headers()

        self.assertEqual(headers["Authorization"], "Bearer ghp_test")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")

    def test_inspect_github_project_normalizes_project_data(self) -> None:
        readme = base64.b64encode(b"# OfferGraph\nAgent workspace.").decode("ascii")
        client = FakeGitHubClient(
            {
                "/repos/siyuansdsd/OfferGraph": {
                    "full_name": "siyuansdsd/OfferGraph",
                    "html_url": "https://github.com/siyuansdsd/OfferGraph",
                    "description": "Offer hunter agent",
                    "stargazers_count": 12,
                    "forks_count": 3,
                    "watchers_count": 4,
                    "open_issues_count": 5,
                    "language": "Python",
                    "topics": ["agents"],
                    "default_branch": "main",
                    "license": {"spdx_id": "MIT"},
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-06-19T00:00:00Z",
                    "pushed_at": "2026-06-18T00:00:00Z",
                    "archived": False,
                    "visibility": "public",
                },
                "/repos/siyuansdsd/OfferGraph/pulls": [
                    {
                        "number": 6,
                        "title": "Add image matcher",
                        "state": "open",
                        "html_url": "https://github.com/siyuansdsd/OfferGraph/pull/6",
                        "user": {"login": "siyuansdsd"},
                        "created_at": "2026-06-18T00:00:00Z",
                        "updated_at": "2026-06-19T00:00:00Z",
                        "merged_at": None,
                    }
                ],
                "/repos/siyuansdsd/OfferGraph/issues": [
                    {
                        "number": 7,
                        "title": "Track GitHub project progress",
                        "state": "open",
                        "html_url": "https://github.com/siyuansdsd/OfferGraph/issues/7",
                        "user": {"login": "siyuansdsd"},
                        "created_at": "2026-06-18T00:00:00Z",
                        "updated_at": "2026-06-19T00:00:00Z",
                    },
                    {
                        "number": 6,
                        "title": "PR issue wrapper",
                        "pull_request": {},
                    },
                ],
                "/repos/siyuansdsd/OfferGraph/commits": [
                    {
                        "sha": "abcdef123456",
                        "html_url": "https://github.com/siyuansdsd/OfferGraph/commit/abcdef1",
                        "commit": {
                            "message": "tools: image matcher\n\nBody",
                            "author": {
                                "name": "Siyuan",
                                "date": "2026-06-19T00:00:00Z",
                            },
                        },
                    }
                ],
                "/repos/siyuansdsd/OfferGraph/releases": [
                    {
                        "name": "v0.1",
                        "tag_name": "v0.1",
                        "html_url": "https://github.com/siyuansdsd/OfferGraph/releases/tag/v0.1",
                        "published_at": "2026-06-19T00:00:00Z",
                        "prerelease": False,
                    }
                ],
                "/repos/siyuansdsd/OfferGraph/readme": {
                    "content": readme,
                },
            }
        )

        with patch("tools.github_project.load_project_env", return_value=True), patch(
            "tools.github_project.get_env",
            side_effect=lambda name, default=None, load=True: "ghp_test"
            if name == GITHUB_TOKEN_ENV
            else default,
        ):
            report = inspect_github_project(
                "https://github.com/siyuansdsd/OfferGraph",
                client=client,
            )

        self.assertEqual(report.repository["full_name"], "siyuansdsd/OfferGraph")
        self.assertEqual(report.repository["stars"], 12)
        self.assertEqual(report.recent_pull_requests[0]["title"], "Add image matcher")
        self.assertEqual(report.recent_issues[0]["number"], 7)
        self.assertEqual(report.recent_commits[0]["message"], "tools: image matcher")
        self.assertEqual(report.recent_releases[0]["tag_name"], "v0.1")
        self.assertIn("OfferGraph", report.readme_excerpt)
        self.assertEqual(
            client.calls[0]["headers"]["Authorization"],
            "Bearer ghp_test",
        )

    def test_github_project_inspector_saves_report_to_state(self) -> None:
        report = inspect_github_project(
            "siyuansdsd/OfferGraph",
            client=FakeGitHubClient(
                {
                    "/repos/siyuansdsd/OfferGraph": {
                        "full_name": "siyuansdsd/OfferGraph",
                        "html_url": "https://github.com/siyuansdsd/OfferGraph",
                        "stargazers_count": 12,
                        "forks_count": 3,
                        "open_issues_count": 5,
                    },
                    "/repos/siyuansdsd/OfferGraph/pulls": [],
                    "/repos/siyuansdsd/OfferGraph/issues": [],
                    "/repos/siyuansdsd/OfferGraph/commits": [],
                    "/repos/siyuansdsd/OfferGraph/releases": [],
                }
            ),
            include_readme=False,
        )

        with patch(
            "tools.github_project.inspect_github_project",
            return_value=report,
        ), patch("tools.github_project.unique_filename", return_value="github.md"):
            command = github_project_inspector.func(
                "https://github.com/siyuansdsd/OfferGraph",
                {"files": {}},
                "call-1",
            )

        self.assertIn("github.md", command.update["files"])
        self.assertIn("Stars: 12", command.update["files"]["github.md"])
        self.assertEqual(command.update["messages"][0].tool_call_id, "call-1")
        self.assertIn(
            "Inspected GitHub project siyuansdsd/OfferGraph",
            command.update["messages"][0].content,
        )
