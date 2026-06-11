"""Tests for research tools."""

from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx

from tools.research_tools import (
    SearchSummary,
    fetch_markdown_content,
    get_today_str,
    process_search_results,
    sanitize_filename,
    tavily_search,
    think_tool,
    unique_filename,
)


class ResearchToolsTest(TestCase):
    def test_get_today_str_accepts_date(self) -> None:
        self.assertEqual(get_today_str(date(2026, 6, 10)), "Wed Jun 10, 2026")

    def test_sanitize_filename(self) -> None:
        self.assertEqual(sanitize_filename("../Bad File!.txt"), "Bad_File.md")
        self.assertEqual(sanitize_filename(""), "search_result.md")

    def test_unique_filename_adds_suffix(self) -> None:
        self.assertEqual(unique_filename("result.md", uid="abc123"), "result_abc123.md")

    def test_fetch_markdown_content(self) -> None:
        request = httpx.Request("GET", "https://example.com")
        response = httpx.Response(200, request=request, text="<h1>Hello</h1>")
        http_client = Mock()
        http_client.get.return_value = response

        result = fetch_markdown_content("https://example.com", http_client=http_client)

        self.assertIn("Hello", result)
        http_client.get.assert_called_once_with("https://example.com")

    def test_process_search_results_uses_fetcher_and_summarizer(self) -> None:
        results = {
            "results": [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "content": "fallback",
                }
            ]
        }

        processed = process_search_results(
            results,
            fetcher=lambda _: "full content",
            summarizer=lambda _: SearchSummary(
                filename="Example Result.md",
                summary="Short summary",
            ),
            uid_factory=lambda: "uid",
        )

        self.assertEqual(
            processed,
            [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "summary": "Short summary",
                    "filename": "Example_Result_uid.md",
                    "raw_content": "full content",
                }
            ],
        )

    def test_tavily_search_saves_files_to_command(self) -> None:
        with patch(
            "tools.research_tools.run_tavily_search",
            return_value={"results": [{"url": "https://example.com", "title": "Example"}]},
        ), patch(
            "tools.research_tools.process_search_results",
            return_value=[
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "summary": "Short summary",
                    "filename": "example_uid.md",
                    "raw_content": "Full content",
                }
            ],
        ):
            command = tavily_search.func(
                "example query",
                {"files": {}},
                "call-1",
                1,
                "general",
            )

        self.assertIn("example_uid.md", command.update["files"])
        self.assertEqual(command.update["messages"][0].tool_call_id, "call-1")
        self.assertIn("Found 1 result", command.update["messages"][0].content)

    def test_think_tool(self) -> None:
        result = think_tool.invoke({"reflection": "Need more evidence."})

        self.assertEqual(result, "Reflection recorded: Need more evidence.")
