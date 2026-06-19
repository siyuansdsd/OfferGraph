"""Tests for memory tools."""

from unittest import TestCase
from unittest.mock import Mock, patch

from agent.memory.models import MemoryRecord
from tools.memory_tools import memory_record_browser_trace, memory_search


class MemoryToolsTest(TestCase):
    def test_memory_search_returns_serialized_records(self) -> None:
        record = MemoryRecord(
            module="linkedin",
            kind="browser_trace",
            task="Create post",
            summary="Draft prepared.",
            success=True,
            tags=["linkedin"],
            payload={"status": "draft_ready"},
        )
        store = Mock()
        store.search.return_value = [record]

        with patch("tools.memory_tools.memory_enabled", return_value=True), patch(
            "tools.memory_tools.get_default_memory_store",
            return_value=store,
        ):
            result = memory_search.invoke(
                {
                    "query": "post",
                    "module": "linkedin",
                    "tags": ["linkedin"],
                    "include_payload": True,
                }
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["records"][0]["payload"]["status"], "draft_ready")
        store.search.assert_called_once_with(
            query="post",
            module="linkedin",
            kind=None,
            tags=["linkedin"],
            limit=5,
        )

    def test_memory_search_reports_disabled(self) -> None:
        with patch("tools.memory_tools.memory_enabled", return_value=False):
            result = memory_search.invoke({"query": "anything"})

        self.assertEqual(result["status"], "disabled")
        self.assertEqual(result["records"], [])

    def test_memory_record_browser_trace_returns_record_id(self) -> None:
        record = MemoryRecord(
            module="browser",
            kind="browser_trace",
            task="Open page",
            summary="Browser trace succeeded.",
            success=True,
        )

        with patch(
            "tools.memory_tools.record_browser_trace",
            return_value=record,
        ) as record_mock:
            result = memory_record_browser_trace.invoke(
                {
                    "task": "Open page",
                    "final_result": "ok",
                    "success": True,
                    "actions": [{"type": "navigate", "label": "Open page"}],
                }
            )

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["id"], record.id)
        record_mock.assert_called_once()
