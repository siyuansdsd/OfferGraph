"""SQLite and JSONL memory storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.memory.models import MemoryRecord
from config.env import PROJECT_ROOT, get_env, load_project_env


MEMORY_ENABLED_ENV = "OFFERGRAPH_MEMORY_ENABLED"
MEMORY_DB_PATH_ENV = "OFFERGRAPH_MEMORY_DB_PATH"
MEMORY_JSONL_PATH_ENV = "OFFERGRAPH_MEMORY_JSONL_PATH"
DEFAULT_MEMORY_DB_PATH = PROJECT_ROOT / "local_data" / "memory" / "offergraph_memory.sqlite3"
DEFAULT_MEMORY_JSONL_PATH = PROJECT_ROOT / "local_data" / "memory" / "events.jsonl"


def memory_enabled() -> bool:
    """Return whether persistent memory writes and reads are enabled."""
    value = get_env(MEMORY_ENABLED_ENV, "true")
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def get_memory_db_path() -> Path:
    """Return the configured SQLite memory path."""
    load_project_env()
    return resolve_project_path(
        get_env(MEMORY_DB_PATH_ENV, load=False),
        default=DEFAULT_MEMORY_DB_PATH,
    )


def get_memory_jsonl_path() -> Path | None:
    """Return the configured JSONL event log path, or None when disabled."""
    load_project_env()
    value = get_env(MEMORY_JSONL_PATH_ENV, load=False)
    if value and value.strip().lower() in {"0", "false", "no", "off", "none"}:
        return None
    return resolve_project_path(value, default=DEFAULT_MEMORY_JSONL_PATH)


def resolve_project_path(value: str | None, *, default: Path) -> Path:
    """Resolve relative paths from the project root."""
    if not value:
        return default
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def get_default_memory_store() -> "SQLiteMemoryStore":
    """Return the default project memory store."""
    return SQLiteMemoryStore(
        db_path=get_memory_db_path(),
        jsonl_path=get_memory_jsonl_path(),
    )


class SQLiteMemoryStore:
    """Durable memory store backed by SQLite, with optional JSONL mirroring."""

    def __init__(
        self,
        db_path: str | Path = DEFAULT_MEMORY_DB_PATH,
        *,
        jsonl_path: str | Path | None = DEFAULT_MEMORY_JSONL_PATH,
    ) -> None:
        self.db_path = Path(db_path).expanduser()
        self.jsonl_path = Path(jsonl_path).expanduser() if jsonl_path else None
        self._initialize()

    def append(self, record: MemoryRecord) -> MemoryRecord:
        """Persist a memory record and return it."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO memory_records (
                    id,
                    created_at,
                    module,
                    kind,
                    task,
                    summary,
                    source_url,
                    success,
                    tags_json,
                    payload_json,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.created_at.isoformat(),
                    record.module,
                    record.kind,
                    record.task,
                    record.summary,
                    record.source_url,
                    _bool_to_int(record.success),
                    json.dumps(record.tags, ensure_ascii=False),
                    json.dumps(record.payload, ensure_ascii=False, default=str),
                    json.dumps(record.metadata, ensure_ascii=False, default=str),
                ),
            )

        self._append_jsonl(record)
        return record

    def get(self, record_id: str) -> MemoryRecord | None:
        """Return one memory record by id."""
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM memory_records WHERE id = ?",
                (record_id,),
            ).fetchone()
        return _record_from_row(row) if row else None

    def search(
        self,
        query: str = "",
        *,
        module: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        """Search memory with lightweight SQL filters."""
        where_clauses: list[str] = []
        params: list[Any] = []
        normalized_query = " ".join(query.split())

        if normalized_query:
            like_query = f"%{normalized_query}%"
            where_clauses.append(
                """
                (
                    task LIKE ?
                    OR summary LIKE ?
                    OR source_url LIKE ?
                    OR tags_json LIKE ?
                    OR payload_json LIKE ?
                    OR metadata_json LIKE ?
                )
                """
            )
            params.extend([like_query] * 6)
        if module:
            where_clauses.append("module = ?")
            params.append(module)
        if kind:
            where_clauses.append("kind = ?")
            params.append(kind)
        for tag in tags or []:
            where_clauses.append("tags_json LIKE ?")
            params.append(f"%{tag}%")

        sql = "SELECT * FROM memory_records"
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 50)))

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(sql, params).fetchall()
        return [_record_from_row(row) for row in rows]

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    module TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    task TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_url TEXT,
                    success INTEGER,
                    tags_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_records_created_at "
                "ON memory_records(created_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_records_module_kind "
                "ON memory_records(module, kind)"
            )

    def _append_jsonl(self, record: MemoryRecord) -> None:
        if self.jsonl_path is None:
            return
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")


def _bool_to_int(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _int_to_bool(value: int | None) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _loads_json(value: str) -> Any:
    return json.loads(value) if value else None


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        created_at=row["created_at"],
        module=row["module"],
        kind=row["kind"],
        task=row["task"],
        summary=row["summary"],
        source_url=row["source_url"],
        success=_int_to_bool(row["success"]),
        tags=_loads_json(row["tags_json"]) or [],
        payload=_loads_json(row["payload_json"]) or {},
        metadata=_loads_json(row["metadata_json"]) or {},
    )
