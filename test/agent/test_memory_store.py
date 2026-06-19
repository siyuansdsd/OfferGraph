"""Tests for persistent memory storage."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from agent.memory.models import MemoryRecord
from agent.memory.store import (
    DEFAULT_MEMORY_DB_PATH,
    SQLiteMemoryStore,
    get_memory_jsonl_path,
    memory_enabled,
    resolve_project_path,
)
from config.env import PROJECT_ROOT


class MemoryStoreTest(TestCase):
    def test_append_get_and_search_records(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "memory.sqlite3"
            jsonl_path = Path(tmp_dir) / "events.jsonl"
            store = SQLiteMemoryStore(db_path, jsonl_path=jsonl_path)
            record = MemoryRecord(
                module="linkedin",
                kind="browser_trace",
                task="Create MiniMax LinkedIn post",
                summary="LinkedIn draft was prepared.",
                source_url="https://www.linkedin.com/feed/",
                success=True,
                tags=["linkedin", "playwright"],
                payload={"status": "draft_ready"},
            )

            store.append(record)

            self.assertEqual(store.get(record.id), record)
            matches = store.search("MiniMax", module="linkedin", tags=["playwright"])
            self.assertEqual([match.id for match in matches], [record.id])
            self.assertTrue(jsonl_path.exists())
            self.assertIn(record.id, jsonl_path.read_text(encoding="utf-8"))

    def test_resolve_project_path_uses_project_root_for_relative_paths(self) -> None:
        self.assertEqual(
            resolve_project_path("local_data/memory/test.sqlite3", default=DEFAULT_MEMORY_DB_PATH),
            PROJECT_ROOT / "local_data" / "memory" / "test.sqlite3",
        )

    def test_memory_enabled_reads_feature_flag(self) -> None:
        with patch("agent.memory.store.get_env", return_value="false"):
            self.assertFalse(memory_enabled())

        with patch("agent.memory.store.get_env", return_value="true"):
            self.assertTrue(memory_enabled())

    def test_jsonl_path_can_be_disabled(self) -> None:
        with patch("agent.memory.store.load_project_env"), patch(
            "agent.memory.store.get_env",
            return_value="none",
        ):
            self.assertIsNone(get_memory_jsonl_path())
