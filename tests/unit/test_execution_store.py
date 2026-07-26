"""Unit tests for services.execution_store.ExecutionStore."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    error_message: str | None = None,
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
        error_message=error_message,
    )


@pytest.fixture
def store(tmp_path: Path) -> ExecutionStore:
    s = ExecutionStore(tmp_path / "scheduler.sqlite")
    s.init()
    return s


def test_executions_add_list_order(store: ExecutionStore):
    t0 = _utc(datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc))
    t1 = _utc(datetime(2026, 7, 19, 11, 0, 0, tzinfo=timezone.utc))
    t2 = _utc(datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc))
    store.add(_exec("a", started_at=t0, task_name="old"))
    store.add(_exec("b", started_at=t2, task_name="new"))
    store.add(_exec("c", started_at=t1, task_name="mid"))
    rows = store.list(limit=10)
    assert [r.id for r in rows] == ["b", "c", "a"]


def test_executions_trim_to_1000(store: ExecutionStore):
    base = _utc(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    for i in range(1005):
        store.add(
            _exec(
                f"run-{i:04d}",
                started_at=base + timedelta(seconds=i),
                task_name=f"t{i}",
            )
        )
    rows = store.list(limit=2000)
    assert len(rows) == 1000
    # Newest retained
    assert rows[0].id == "run-1004"
    ids = {r.id for r in rows}
    assert "run-0000" not in ids
    assert "run-0004" not in ids
    assert "run-0005" in ids


def test_finish_writes_status_and_finished_at(store: ExecutionStore):
    store.add(_exec("run-f", status="running"))
    store.finish("run-f", "success", error=None)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].finished_at is not None
    assert rows[0].error_message is None

    store.add(_exec("run-e", status="running"))
    store.finish("run-e", "failed", error="boom")
    by_id = {r.id: r for r in store.list()}
    assert by_id["run-e"].status == "failed"
    assert by_id["run-e"].error_message == "boom"
    assert by_id["run-e"].finished_at is not None


def test_init_archives_orphaned_running_rows_as_failed(tmp_path: Path):
    """崩溃恢复：进程异常退出后残留 status='running' / finished_at IS NULL 的行，
    重启时 init() 必须归档为 failed 终态，否则后续入场永远 busy。

    覆盖要点：status -> failed、finished_at 被写入、error_message 使用 fallback
    文案「应用异常退出」。
    """
    db = tmp_path / "scheduler.sqlite"
    # 第一次进程：写入两条 running 行（finished_at=None），未调 finish 即"崩溃"
    first = ExecutionStore(db)
    first.init()
    first.add(
        _exec(
            "r-orphan-1",
            started_at=_utc(datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc)),
        )
    )
    first.add(
        _exec(
            "r-orphan-2",
            started_at=_utc(datetime(2026, 7, 19, 11, 0, 0, tzinfo=timezone.utc)),
        )
    )
    del first

    # 重启：init 触发崩溃恢复
    reopened = ExecutionStore(db)
    reopened.init()

    by_id = {r.id: r for r in reopened.list()}
    assert len(by_id) == 2
    for rid in ("r-orphan-1", "r-orphan-2"):
        assert by_id[rid].status == "failed"
        assert by_id[rid].finished_at is not None
        assert by_id[rid].error_message == "应用异常退出"


def test_init_preserves_existing_error_message_on_running_orphans(tmp_path: Path):
    """崩溃恢复：running 残留行若已带 error_message（崩溃前部分写入），init() 必须
    保留既有错误信息，不被「应用异常退出」覆盖——COALESCE(error_message, fallback) 语义。

    同场景覆盖：未带 error_message 的行仍走 fallback 文案。
    """
    db = tmp_path / "scheduler.sqlite"
    first = ExecutionStore(db)
    first.init()
    first.add(
        _exec(
            "r-with-err",
            started_at=_utc(datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)),
            error_message="崩溃前写入的半成品错误",
        )
    )
    first.add(
        _exec(
            "r-no-err",
            started_at=_utc(datetime(2026, 7, 19, 12, 30, 0, tzinfo=timezone.utc)),
        )
    )
    del first

    reopened = ExecutionStore(db)
    reopened.init()

    by_id = {r.id: r for r in reopened.list()}
    assert by_id["r-with-err"].status == "failed"
    assert by_id["r-with-err"].finished_at is not None
    # 既有 error_message 保留，未被 fallback 覆盖
    assert by_id["r-with-err"].error_message == "崩溃前写入的半成品错误"
    # 无 error_message 的行使用 fallback
    assert by_id["r-no-err"].status == "failed"
    assert by_id["r-no-err"].error_message == "应用异常退出"
    assert by_id["r-no-err"].finished_at is not None
