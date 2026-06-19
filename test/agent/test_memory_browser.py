"""Tests for browser memory helpers."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent.memory.browser import build_browser_trace_record, record_browser_trace
from agent.memory.models import BrowserAction, BrowserTrace
from agent.memory.store import SQLiteMemoryStore


class BrowserMemoryTest(TestCase):
    def test_build_browser_trace_record(self) -> None:
        trace = BrowserTrace(
            task="Open LinkedIn composer",
            url="https://www.linkedin.com/feed/",
            actions=[BrowserAction(type="click", label="Start a post")],
            final_result="draft_ready",
            success=True,
            extracted_data={"status": "draft_ready"},
        )

        record = build_browser_trace_record(
            trace,
            module="linkedin",
            tags=["linkedin", "playwright"],
        )

        self.assertEqual(record.module, "linkedin")
        self.assertEqual(record.kind, "browser_trace")
        self.assertTrue(record.success)
        self.assertIn("Open LinkedIn composer", record.summary)
        self.assertEqual(record.payload["extracted_data"]["status"], "draft_ready")
        self.assertEqual(record.tags, ["browser", "playwright", "linkedin"])

    def test_record_browser_trace_persists_when_enabled(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = SQLiteMemoryStore(
                Path(tmp_dir) / "memory.sqlite3",
                jsonl_path=None,
            )
            with patch("agent.memory.browser.memory_enabled", return_value=True):
                record = record_browser_trace(
                    task="Open LinkedIn composer",
                    url="https://www.linkedin.com/feed/",
                    actions=[{"type": "navigate", "label": "Open feed"}],
                    final_result="draft_ready",
                    success=True,
                    module="linkedin",
                    tags=["linkedin"],
                    store=store,
                )

            self.assertIsNotNone(record)
            assert record is not None
            stored = store.get(record.id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.module, "linkedin")

    def test_record_browser_trace_returns_none_when_disabled(self) -> None:
        with patch("agent.memory.browser.memory_enabled", return_value=False):
            record = record_browser_trace(
                task="Open browser",
                final_result="skipped",
                success=False,
            )

        self.assertIsNone(record)
