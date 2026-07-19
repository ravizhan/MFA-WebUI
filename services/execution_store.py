"""SQLite persistence for scheduler executions and occurrence claims."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import aiosqlite

from models.scheduler import TaskExecution

logger = logging.getLogger(__name__)

EXECUTIONS_MAX_RECORDS = 1000
CLAIM_GRACE = timedelta(minutes=15)
CLAIM_RETENTION = timedelta(days=35)
CLAIM_LEASE = timedelta(seconds=30)

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

_CREATE_CLAIMS = """
CREATE TABLE IF NOT EXISTS scheduler_occurrence_claims (
    occurrence_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    scheduled_for TEXT NOT NULL,
    origin TEXT NOT NULL,
    state TEXT NOT NULL,
    run_id TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    lease_until TEXT,
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
    """Owns scheduler.sqlite tables: executions + occurrence_claims."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    async def init(self) -> None:
        """Create tables/indexes, recover incomplete claims, prune old terminal claims."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            # 旧 schema 重置：缺 origin 列的 executions 表直接丢弃（无迁移层，历史清空）
            cursor = await db.execute("PRAGMA table_info(scheduler_executions)")
            columns = {row[1] for row in await cursor.fetchall()}
            if columns and "origin" not in columns:
                logger.warning("检测到旧版 executions 表，已按新 schema 重建（历史记录清空）")
                await db.execute("DROP TABLE scheduler_executions")
            await db.execute(_CREATE_EXECUTIONS)
            await db.execute(_CREATE_CLAIMS)
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
            await self._recover_claims(db)
            await self._cleanup_old_claims(db)
            await db.commit()

    async def _recover_claims(self, db: aiosqlite.Connection) -> None:
        now = _utc_now()
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT occurrence_id, scheduled_for
            FROM scheduler_occurrence_claims
            WHERE state IN ('claimed', 'running') AND finished_at IS NULL
            """
        ) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            scheduled_for = _from_iso(row["scheduled_for"])
            if scheduled_for is not None and now - scheduled_for <= CLAIM_GRACE:
                await db.execute(
                    "DELETE FROM scheduler_occurrence_claims WHERE occurrence_id = ?",
                    (row["occurrence_id"],),
                )
            else:
                await db.execute(
                    """
                    UPDATE scheduler_occurrence_claims
                    SET state = 'abandoned', finished_at = ?
                    WHERE occurrence_id = ?
                    """,
                    (_to_iso(now), row["occurrence_id"]),
                )

    async def _cleanup_old_claims(self, db: aiosqlite.Connection) -> None:
        cutoff = _to_iso(_utc_now() - CLAIM_RETENTION)
        await db.execute(
            """
            DELETE FROM scheduler_occurrence_claims
            WHERE state IN ('done', 'abandoned')
              AND finished_at IS NOT NULL
              AND finished_at < ?
            """,
            (cutoff,),
        )

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

    async def finish(
        self, run_id: str, status: str, error: str | None = None
    ) -> None:
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

    async def try_claim(
        self,
        occurrence_id: str,
        task_id: str,
        scheduled_for: datetime,
        origin: str,
        run_id: str,
    ) -> bool:
        now = _utc_now()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO scheduler_occurrence_claims (
                    occurrence_id, task_id, scheduled_for, origin, state,
                    run_id, claimed_at, lease_until, finished_at
                ) VALUES (?, ?, ?, ?, 'claimed', ?, ?, ?, NULL)
                """,
                (
                    occurrence_id,
                    task_id,
                    _to_iso(scheduled_for),
                    origin,
                    run_id,
                    _to_iso(now),
                    _to_iso(now + CLAIM_LEASE),
                ),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def mark_running(self, occurrence_id: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE scheduler_occurrence_claims
                SET state = 'running', lease_until = NULL
                WHERE occurrence_id = ?
                """,
                (occurrence_id,),
            )
            await db.commit()

    async def finish_claim(
        self, occurrence_id: str, abandoned: bool = False
    ) -> None:
        state = "abandoned" if abandoned else "done"
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE scheduler_occurrence_claims
                SET state = ?, finished_at = ?, lease_until = NULL
                WHERE occurrence_id = ?
                """,
                (state, _to_iso(_utc_now()), occurrence_id),
            )
            await db.commit()
