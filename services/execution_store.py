"""SQLite persistence for scheduler execution history."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import aiosqlite

from models.scheduler import TaskExecution

logger = logging.getLogger(__name__)

EXECUTIONS_MAX_RECORDS = 1000

_CREATE_EXECUTIONS = """
CREATE TABLE IF NOT EXISTS scheduler_executions (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    task_name TEXT NOT NULL,
    origin TEXT NOT NULL,
    occurrence_id TEXT,
    scheduled_for TEXT,
    status TEXT NOT NULL,
    blocker_run_id TEXT,
    blocker_task_name TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
)
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_to_execution(row: aiosqlite.Row) -> TaskExecution:
    return TaskExecution(
        id=row["id"],
        task_id=row["task_id"],
        task_name=row["task_name"],
        origin=row["origin"],
        occurrence_id=row["occurrence_id"],
        scheduled_for=_from_iso(row["scheduled_for"]),
        status=row["status"],
        blocker_run_id=row["blocker_run_id"],
        blocker_task_name=row["blocker_task_name"],
        error_message=row["error_message"],
        started_at=_from_iso(row["started_at"]) or _utc_now(),
        finished_at=_from_iso(row["finished_at"]),
    )


class ExecutionStore:
    """Owns scheduler.sqlite executions table."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    async def init(self) -> None:
        """Create tables/indexes."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            # 旧 schema 重置：缺 origin 列的 executions 表直接丢弃（无迁移层，历史清空）
            cursor = await db.execute("PRAGMA table_info(scheduler_executions)")
            columns = {row[1] for row in await cursor.fetchall()}
            if columns and "origin" not in columns:
                logger.warning(
                    "检测到旧版 executions 表，已按新 schema 重建（历史记录清空）"
                )
                await db.execute("DROP TABLE scheduler_executions")
            await db.execute(_CREATE_EXECUTIONS)
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduler_executions_started_at
                ON scheduler_executions(started_at DESC)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduler_executions_task_id
                ON scheduler_executions(task_id)
                """
            )
            # Drop legacy occurrence-claim table if present (claim mechanism removed)
            await db.execute("DROP TABLE IF EXISTS scheduler_occurrence_claims")
            await db.commit()

    async def add(self, execution: TaskExecution) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO scheduler_executions (
                    id, task_id, task_name, origin, occurrence_id, scheduled_for,
                    status, blocker_run_id, blocker_task_name, error_message,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution.id,
                    execution.task_id,
                    execution.task_name,
                    execution.origin,
                    execution.occurrence_id,
                    _to_iso(execution.scheduled_for),
                    execution.status,
                    execution.blocker_run_id,
                    execution.blocker_task_name,
                    execution.error_message,
                    _to_iso(execution.started_at),
                    _to_iso(execution.finished_at),
                ),
            )
            await db.execute(
                """
                DELETE FROM scheduler_executions
                WHERE id NOT IN (
                    SELECT id FROM scheduler_executions
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (EXECUTIONS_MAX_RECORDS,),
            )
            await db.commit()

    async def finish(self, run_id: str, status: str, error: str | None = None) -> None:
        finished_at = _to_iso(_utc_now())
        async with aiosqlite.connect(self._db_path) as db:
            if error is None:
                await db.execute(
                    """
                    UPDATE scheduler_executions
                    SET status = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (status, finished_at, run_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE scheduler_executions
                    SET status = ?, finished_at = ?, error_message = ?
                    WHERE id = ?
                    """,
                    (status, finished_at, error, run_id),
                )
            await db.commit()

    async def list(self, limit: int = 50) -> List[TaskExecution]:
        # Method name shadows builtin list; use typing.List for the annotation.
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM scheduler_executions
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_execution(row) for row in rows]
