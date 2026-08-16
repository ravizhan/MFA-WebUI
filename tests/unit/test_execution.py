"""Tests for maa_worker/execution.py — admission control and sqlite execution records.

worker 保持 None：后台执行协程以「Worker 未就绪」快速失败，断言最终落库状态。
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app_state import AppState
from maa_worker.execution import (
    add_execution,
    finish_execution,
    init_db,
    list_executions,
    submit_manual,
    submit_scheduled,
    stop_active,
)
from models.scheduler import (
    CronTriggerConfig,
    ManualStartPayload,
    ScheduledTask,
    ScheduledTaskDeviceConfig,
    TaskExecution,
)


def make_payload(task_name: str = "Startup") -> ManualStartPayload:
    return ManualStartPayload(
        task_list=[task_name],
        controller_name="AdbController",
        device=ScheduledTaskDeviceConfig(
            controller_name="AdbController",
            device_type="Adb",
            device_address="127.0.0.1:5555",
        ),
        resource_name="main",
    )


def make_task(task_id: str = "task-1", name: str = "定时任务") -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name=name,
        wakeup_enabled=True,
        enabled=True,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
    )


async def _await_active_task(state: AppState) -> None:
    """等待当前活跃执行协程收尾（type-narrowing 辅助）。"""
    task = state.active_execution_task
    assert task is not None
    await task


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    st = AppState()
    st.scheduler_db_path = tmp_path / "scheduler.sqlite"
    init_db(st.scheduler_db_path)
    return st


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def _column_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute("PRAGMA table_info(scheduler_executions)").fetchall()
    return {row[1] for row in rows}


# ---------------------------------------------------------------------------
# 持久化（stdlib sqlite3）
# ---------------------------------------------------------------------------


class TestSqlitePersistence:
    def test_init_db_creates_table_with_new_columns(self, tmp_path: Path):
        db_path = tmp_path / "executions.sqlite"

        init_db(db_path)

        assert "scheduler_executions" in _table_names(db_path)
        columns = _column_names(db_path)
        for column in (
            "origin",
            "occurrence_id",
            "scheduled_for",
            "blocker_run_id",
            "blocker_task_name",
        ):
            assert column in columns

    def test_init_db_is_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "executions.sqlite"
        init_db(db_path)
        init_db(db_path)  # 不抛错

    def test_add_and_list_round_trip_with_new_fields(self, state: AppState):
        scheduled_for = datetime(2026, 8, 16, 1, 2, 3, tzinfo=timezone.utc)
        started_at = datetime(2026, 8, 16, 0, 0, 0, tzinfo=timezone.utc)
        execution = TaskExecution(
            id="run-1",
            task_id="task-1",
            task_name="定时任务",
            origin="native",
            occurrence_id="task-1:2026-08-16T01:02:03+00:00",
            scheduled_for=scheduled_for,
            blocker_task_name="手动任务",
            started_at=started_at,
            status="running",
            error_message=None,
        )

        add_execution(state.scheduler_db_path, execution)

        rows = list_executions(state.scheduler_db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row.id == "run-1"
        assert row.task_id == "task-1"
        assert row.task_name == "定时任务"
        assert row.origin == "native"
        assert row.occurrence_id == "task-1:2026-08-16T01:02:03+00:00"
        assert row.scheduled_for == scheduled_for
        assert row.blocker_task_name == "手动任务"
        assert row.started_at == started_at
        assert row.finished_at is None
        assert row.status == "running"
        assert row.error_message is None

    def test_list_executions_ordered_newest_first(self, state: AppState):
        for index, started in enumerate(
            [
                datetime(2026, 8, 16, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 17, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 8, 18, 0, 0, 0, tzinfo=timezone.utc),
            ]
        ):
            add_execution(
                state.scheduler_db_path,
                TaskExecution(
                    id=f"run-{index}",
                    task_id=None,
                    task_name="手动任务",
                    origin="manual",
                    started_at=started,
                    status="running",
                ),
            )

        rows = list_executions(state.scheduler_db_path)
        assert [row.id for row in rows] == ["run-2", "run-1", "run-0"]

    def test_list_executions_missing_db_returns_empty(self, tmp_path: Path):
        assert list_executions(tmp_path / "nope.sqlite") == []

    def test_finish_execution_updates_status_and_finished_at(self, state: AppState):
        add_execution(
            state.scheduler_db_path,
            TaskExecution(
                id="run-1",
                task_id="task-1",
                task_name="定时任务",
                origin="in_app",
                started_at=datetime(2026, 8, 16, 0, 0, 0, tzinfo=timezone.utc),
                status="running",
            ),
        )

        finish_execution(state.scheduler_db_path, "run-1", "success", error="一切正常")

        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "success"
        assert row.finished_at is not None
        assert row.error_message == "一切正常"


# ---------------------------------------------------------------------------
# submit_manual — 准入与冲突
# ---------------------------------------------------------------------------


class TestSubmitManual:
    async def test_first_accepted_second_conflicts_busy_manual(self, state: AppState):
        first = await submit_manual(state, make_payload("手动任务A"))
        assert first.accepted is True
        assert first.run_id is not None
        assert first.conflict is None
        assert state.active_run is not None

        second = await submit_manual(state, make_payload("手动任务B"))
        assert second.accepted is False
        assert second.run_id is None
        assert second.conflict is not None
        assert second.conflict.code == "busy_manual"
        assert second.conflict.active_run_id == first.run_id
        assert second.conflict.active_task_name == "手动任务A"
        assert second.conflict.active_origin == "manual"

        # 等待后台协程自然收尾（worker=None → failed）
        await _await_active_task(state)
        assert state.active_run is None
        rows = list_executions(state.scheduler_db_path)
        assert len(rows) == 1
        assert rows[0].id == first.run_id
        assert rows[0].status == "failed"
        assert "Worker 未就绪" in rows[0].error_message

    async def test_update_in_progress_conflict(self, state: AppState):
        state.update_in_progress = True

        admission = await submit_manual(state, make_payload())

        assert admission.accepted is False
        assert admission.run_id is not None
        assert admission.conflict is not None
        assert admission.conflict.code == "update_in_progress"
        assert state.active_run is None
        assert list_executions(state.scheduler_db_path) == []

    async def test_stop_active_with_active_run_returns_true(self, state: AppState):
        await submit_manual(state, make_payload())
        assert await stop_active(state) is True
        assert state.active_run is not None
        assert state.active_run.stop_requested is True
        await _await_active_task(state)


# ---------------------------------------------------------------------------
# submit_scheduled — 迟到/忙/更新中
# ---------------------------------------------------------------------------


class TestSubmitScheduled:
    async def test_native_late_marks_missed_deadline_and_writes_row(
        self, state: AppState
    ):
        task = make_task()
        scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=16)

        admission = await submit_scheduled(
            state, task, origin="native", scheduled_for=scheduled_for
        )

        assert admission.accepted is False
        assert admission.skip_status == "missed_deadline"
        assert admission.conflict is None
        assert state.active_run is None
        rows = list_executions(state.scheduler_db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row.id == admission.run_id
        assert row.status == "missed_deadline"
        assert row.origin == "native"
        assert row.task_id == task.id
        assert row.occurrence_id == (
            f"{task.id}:{scheduled_for.astimezone(timezone.utc).isoformat()}"
        )
        assert row.scheduled_for == scheduled_for
        assert row.finished_at is not None

    async def test_native_not_late_is_accepted(self, state: AppState):
        task = make_task()
        scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=14)

        admission = await submit_scheduled(
            state, task, origin="native", scheduled_for=scheduled_for
        )

        assert admission.accepted is True
        assert admission.run_id is not None
        await _await_active_task(state)
        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "failed"  # worker=None，自然失败收尾

    async def test_skipped_busy_manual_while_manual_run_active(self, state: AppState):
        task = make_task()
        first = await submit_manual(state, make_payload("手动任务A"))
        assert first.accepted is True

        admission = await submit_scheduled(state, task, origin="in_app")

        assert admission.accepted is False
        assert admission.skip_status == "skipped_busy_manual"
        assert admission.run_id is not None
        rows = list_executions(state.scheduler_db_path)
        by_id = {row.id: row for row in rows}
        skip = by_id[admission.run_id]
        assert skip.status == "skipped_busy_manual"
        assert skip.task_id == task.id
        assert skip.origin == "in_app"
        assert skip.blocker_task_name == "手动任务A"
        await _await_active_task(state)
        assert state.active_run is None

    async def test_skipped_busy_scheduled_while_scheduled_run_active(
        self, state: AppState
    ):
        first = await submit_scheduled(state, make_task("task-a"), origin="in_app")
        assert first.accepted is True

        admission = await submit_scheduled(state, make_task("task-b"), origin="in_app")

        assert admission.accepted is False
        assert admission.skip_status == "skipped_busy_scheduled"
        assert state.active_run is not None
        await _await_active_task(state)

    async def test_skipped_update_in_progress(self, state: AppState):
        state.update_in_progress = True
        task = make_task()

        admission = await submit_scheduled(state, task, origin="in_app")

        assert admission.accepted is False
        assert admission.skip_status == "skipped_update_in_progress"
        row = list_executions(state.scheduler_db_path)[0]
        assert row.status == "skipped_update_in_progress"


# ---------------------------------------------------------------------------
# stop_active / 取消清理
# ---------------------------------------------------------------------------


class TestStopAndCancel:
    async def test_stop_active_without_active_returns_false(self, state: AppState):
        assert await stop_active(state) is False

    async def test_cancel_active_clears_slot_and_marks_stopped(self, state: AppState):
        admission = await submit_manual(state, make_payload())
        assert state.active_run is not None

        task = state.active_execution_task
        assert task is not None
        task.cancel()
        # 让取消回调（清槽 + 补记 stopped）执行
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert state.active_run is None
        assert state.active_execution_task is None
        rows = list_executions(state.scheduler_db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row.id == admission.run_id
        assert row.status == "stopped"
        assert "取消" in row.error_message
