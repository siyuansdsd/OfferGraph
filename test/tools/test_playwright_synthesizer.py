"""Tests for Playwright tool synthesis from memory traces."""

from unittest import TestCase
from unittest.mock import Mock, patch

from agent.memory.models import MemoryRecord
from tools.playwright_synthesizer import (
    playwright_tool_synthesizer,
    synthesize_playwright_recipe,
)


class PlaywrightSynthesizerTest(TestCase):
    def test_synthesize_playwright_recipe_counts_stable_selectors(self) -> None:
        record = MemoryRecord(
            module="linkedin_jobs",
            kind="browser_trace",
            task="Explore jobs",
            summary="ok",
            source_url="https://www.linkedin.com/jobs/search/",
            success=True,
            tags=["linkedin-jobs-explorer"],
            payload={
                "actions": [
                    {
                        "type": "navigate",
                        "label": "Open jobs",
                        "success": True,
                    },
                    {
                        "type": "click",
                        "label": "Open Easy Apply modal",
                        "selector": 'button:has-text("Easy Apply")',
                        "success": True,
                    },
                    {
                        "type": "click",
                        "label": "Missing button",
                        "selector": "button.missing",
                        "success": False,
                    },
                ],
                "extracted_data": {"jobs": [{"title": "AI Engineer"}]},
            },
        )

        recipe = synthesize_playwright_recipe([record])

        self.assertEqual(recipe["success_count"], 1)
        self.assertEqual(recipe["failure_count"], 0)
        self.assertEqual(
            recipe["stable_selectors"][0]["selector"],
            'button:has-text("Easy Apply")',
        )
        self.assertEqual(recipe["common_extracted_data"][0]["key"], "jobs")
        self.assertIn("tools.playwright_template", recipe["recommended_flow"][0])

    def test_playwright_tool_synthesizer_reads_memory_store(self) -> None:
        record = MemoryRecord(
            module="linkedin_jobs",
            kind="browser_trace",
            task="Explore jobs",
            summary="ok",
            success=True,
            tags=["linkedin-jobs-explorer"],
            payload={"actions": [], "extracted_data": {}},
        )
        store = Mock()
        store.search.return_value = [record]

        with patch("tools.playwright_synthesizer.memory_enabled", return_value=True), patch(
            "tools.playwright_synthesizer.get_default_memory_store",
            return_value=store,
        ):
            result = playwright_tool_synthesizer.invoke(
                {
                    "query": "AI Engineer",
                    "module": "linkedin_jobs",
                    "tags": ["linkedin-jobs-explorer"],
                }
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["trace_count"], 1)
        self.assertEqual(result["source_record_ids"], [record.id])
        store.search.assert_called_once_with(
            query="AI Engineer",
            module="linkedin_jobs",
            kind="browser_trace",
            tags=["linkedin-jobs-explorer"],
            limit=10,
        )

    def test_playwright_tool_synthesizer_reports_disabled_memory(self) -> None:
        with patch("tools.playwright_synthesizer.memory_enabled", return_value=False):
            result = playwright_tool_synthesizer.invoke({})

        self.assertEqual(result["status"], "disabled")
        self.assertIsNone(result["recipe"])
