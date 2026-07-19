"""Unit tests for services.execution_store.ExecutionStore."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from models.scheduler import TaskExecution
from services.execution_store import ExecutionStore


def _utc(dt: datetime | None = None) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _exec(
    run_id: str,
    *,
    status: str = "running",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    task_id: str | None = "t1",
    task_name: str = "task",
    origin: str = "in_app",
) -> TaskExecution:
    now = started_at or _utc()
    return TaskExecution(
        id=run_id,
        task_id=task_id,
        task_name=task_name,
        origin=origin,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        started_at=now,
        finished_at=finished_at,
    )


@pytest.fixture
async def store(tmp_path: Path) -> ExecutionStore:
    s = ExecutionStore(tmp_path / "scheduler.sqlite")
    await s.init()
    return s


@pytest.mark.asyncio
async def test_init_idempotent(tmp_path: Path):
    path = tmp_path / "scheduler.sqlite"
    s = ExecutionStore(path)
    await s.init()
    await s.init()
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cur:
            names = [row[0] for row in await cur.fetchall()]
    assert "scheduler_executions" in names
    assert "scheduler_occurrence_claims" not in names


@pytest.mark.asyncio
async def test_init_drops_legacy_occurrence_claims_table(tmp_path: Path):
    path = tmp_path / "scheduler.sqlite"
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """
            CREATE TABLE scheduler_occurrence_claims (
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
        )
        await db.execute(
            "INSERT INTO scheduler_occurrence_claims VALUES "
            "('occ','t1','2026-01-01','in_app','claimed','r1','2026-01-01',NULL,NULL)"
        )
        await db.commit()
    s = ExecutionStore(path)
    await s.init()
    async with aiosqlite.connect(path) as db:
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("scheduler_occurrence_claims",),
        ) as cur:
            row = await cur.fetchone()
    assert row is None


@pytest.mark.asyncio
async def test_init_drops_legacy_executions_schema(tmp_path: Path):
    path = tmp_path / "scheduler.sqlite"
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "CREATE TABLE scheduler_executions ("
            "id TEXT PRIMARY KEY, task_id TEXT NOT NULL, task_name TEXT NOT NULL,"
            "started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,"
            "error_message TEXT)"
        )
        await db.execute(
            "INSERT INTO scheduler_executions VALUES ('x','t','n','2020-01-01',NULL,'success',NULL)"
        )
        await db.commit()
    s = ExecutionStore(path)
    await s.init()
    async with aiosqlite.connect(path) as db:
        async with db.execute("PRAGMA table_info(scheduler_executions)") as cur:
            columns = {row[1] for row in await cur.fetchall()}
        async with db.execute("SELECT COUNT(*) FROM scheduler_executions") as cur:
            (count,) = await cur.fetchone()
    assert "origin" in columns
    assert count == 0


@pytest.mark.asyncio
async def test_executions_add_list_order(store: ExecutionStore):
    t0 = _utc(datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc))
    t1 = _utc(datetime(2026, 7, 19, 11, 0, 0, tzinfo=timezone.utc))
    t2 = _utc(datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc))
    await store.add(_exec("a", started_at=t0, task_name="old"))
    await store.add(_exec("b", started_at=t2, task_name="new"))
    await store.add(_exec("c", started_at=t1, task_name="mid"))
    rows = await store.list(limit=10)
    assert [r.id for r in rows] == ["b", "c", "a"]


@pytest.mark.asyncio
async def test_executions_trim_to_1000(store: ExecutionStore):
    base = _utc(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    for i in range(1005):
        await store.add(
            _exec(
                f"run-{i:04d}",
                started_at=base + timedelta(seconds=i),
                task_name=f"t{i}",
            )
        )
    rows = await store.list(limit=2000)
    assert len(rows) == 1000
    # Newest retained
    assert rows[0].id == "run-1004"
    ids = {r.id for r in rows}
    assert "run-0000" not in ids
    assert "run-0004" not in ids
    assert "run-0005" in ids


@pytest.mark.asyncio
async def test_finish_writes_status_and_finished_at(store: ExecutionStore):
    await store.add(_exec("run-f", status="running"))
    await store.finish("run-f", "success", error=None)
    rows = await store.list()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].finished_at is not None
    assert rows[0].error_message is None

    await store.add(_exec("run-e", status="running"))
    await store.finish("run-e", "failed", error="boom")
    by_id = {r.id: r for r in await store.list()}
    assert by_id["run-e"].status == "failed"
    assert by_id["run-e"].error_message == "boom"
    assert by_id["run-e"].finished_at is not None
