"""Tests for research tools."""

from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx

from tools.research_tools import (
    SEARCH_SUMMARIZER_MODEL_ENV,
    TAVILY_API_KEY_ENV,
    SearchSummary,
    fetch_markdown_content,
    get_today_str,
    process_search_results,
    run_tavily_search,
    sanitize_filename,
    summarize_webpage_content,
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

    def test_run_tavily_search_reads_tavily_api_key_from_env(self) -> None:
        fake_client = Mock()
        fake_client.search.return_value = {"results": []}

        with patch.dict("os.environ", {TAVILY_API_KEY_ENV: "test-key"}), patch(
            "tools.research_tools.load_project_env",
            return_value=True,
        ), patch("tools.research_tools.TavilyClient", return_value=fake_client) as client_cls:
            result = run_tavily_search("query", max_results=2, topic="news")

        self.assertEqual(result, {"results": []})
        client_cls.assert_called_once_with(api_key="test-key")
        fake_client.search.assert_called_once_with(
            "query",
            max_results=2,
            include_raw_content=True,
            topic="news",
        )

    def test_summarize_webpage_content_reads_model_from_env(self) -> None:
        structured_model = Mock()
        structured_model.invoke.return_value = {
            "filename": "summary.md",
            "summary": "Short summary",
        }
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with patch.dict("os.environ", {SEARCH_SUMMARIZER_MODEL_ENV: "test:model"}), patch(
            "tools.research_tools.load_project_env",
            return_value=True,
        ), patch("tools.research_tools.init_chat_model", return_value=model) as init_mock:
            summary = summarize_webpage_content("long webpage content")

        init_mock.assert_called_once_with(model="test:model")
        self.assertEqual(summary.filename, "summary.md")
        self.assertEqual(summary.summary, "Short summary")

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
