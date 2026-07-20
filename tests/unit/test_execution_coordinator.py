"""Unit tests for services.execution_coordinator.ExecutionCoordinator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app_state import ActiveRun, AppState
from models.scheduler import (
    CronTriggerConfig,
    ManualStartPayload,
    ScheduledTask,
    ScheduledTaskDeviceConfig,
)
from services.execution_coordinator import ExecutionCoordinator, MANUAL_TASK_NAME
from services.execution_store import ExecutionStore


DEVICE = ScheduledTaskDeviceConfig(
    controller_name="ADB",
    device_type="Adb",
    device_address="127.0.0.1:5555",
)


def _manual_payload(**overrides) -> ManualStartPayload:
    data = {
        "task_list": ["Main"],
        "task_options": {"Main": {}},
        "preTasks": [],
        "controller_name": "ADB",
        "device": DEVICE,
        "resource_name": "Official",
    }
    data.update(overrides)
    return ManualStartPayload(**data)


def _scheduled(
    task_id: str = "task-1",
    name: str = "每日任务",
    *,
    cron: str = "0 9 * * *",
) -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name=name,
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
        task_options={"Main": {}},
        controller_name="ADB",
        device=DEVICE,
        resource_name="Official",
    )


def _fake_worker():
    tasks = SimpleNamespace(
        start=MagicMock(return_value=True),
        stop=MagicMock(),
    )
    device = SimpleNamespace(
        reset_connection_state=MagicMock(),
        build_device_model_from_config=MagicMock(return_value=object()),
        connect=MagicMock(return_value=True),
        set_resource=MagicMock(return_value=True),
    )
    events = SimpleNamespace(
        send_log=MagicMock(),
        send_notification=MagicMock(),
    )
    return SimpleNamespace(
        tasks=tasks,
        device=device,
        events=events,
        interface=None,
    )


@pytest.fixture
def store(tmp_path: Path) -> ExecutionStore:
    s = ExecutionStore(tmp_path / "scheduler.sqlite")
    s.init()
    return s


@pytest.fixture
def worker():
    return _fake_worker()


@pytest.fixture
def state(tmp_path: Path, worker) -> AppState:
    s = AppState(tmp_path)
    s.worker = worker
    s.device.connected = True
    s.device.configuration_locked = True
    s.device.controller_name = "ADB"
    s.device.current_resource_name = "Official"
    s.task.running = False
    s.task.last_status = "success"
    s.task.last_error = None
    return s


@pytest.fixture
def coord(store: ExecutionStore, state: AppState) -> ExecutionCoordinator:
    return ExecutionCoordinator(state, store)


@pytest.mark.asyncio
async def test_manual_manual_conflict_busy_manual(
    coord: ExecutionCoordinator, state: AppState, store
):
    state.active_run = ActiveRun(
        run_id="active-manual",
        origin="manual",
        task_name=MANUAL_TASK_NAME,
        occurrence_id=None,
    )
    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is False
    assert result.conflict is not None
    assert result.conflict.code == "busy_manual"
    assert result.conflict.active_run_id == "active-manual"
    assert result.conflict.active_task_name == MANUAL_TASK_NAME
    assert "手动" in result.conflict.message
    assert store.list() == []


@pytest.mark.asyncio
async def test_scheduled_while_manual_skipped_busy_manual(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore
):
    state.active_run = ActiveRun(
        run_id="m1",
        origin="manual",
        task_name=MANUAL_TASK_NAME,
        occurrence_id=None,
    )
    result = await coord.submit_scheduled(_scheduled(), origin="in_app")
    assert result.accepted is False
    assert result.skip_status == "skipped_busy_manual"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "skipped_busy_manual"
    assert rows[0].blocker_run_id == "m1"
    assert rows[0].blocker_task_name == MANUAL_TASK_NAME


@pytest.mark.asyncio
async def test_manual_while_scheduled_conflict_busy_scheduled(
    coord: ExecutionCoordinator, state: AppState
):
    state.active_run = ActiveRun(
        run_id="s1",
        origin="in_app",
        task_name="定时甲",
        occurrence_id="occ",
    )
    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is False
    assert result.conflict is not None
    assert result.conflict.code == "busy_scheduled"
    assert result.conflict.active_task_name == "定时甲"
    assert "定时" in result.conflict.message


@pytest.mark.asyncio
async def test_two_scheduled_different_tasks_skipped_busy_scheduled(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore
):
    state.active_run = ActiveRun(
        run_id="s1",
        origin="in_app",
        task_name="任务A",
        occurrence_id="a:occ",
    )
    result = await coord.submit_scheduled(
        _scheduled(task_id="task-b", name="任务B"), origin="in_app"
    )
    assert result.accepted is False
    assert result.skip_status == "skipped_busy_scheduled"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "skipped_busy_scheduled"
    assert rows[0].blocker_task_name == "任务A"


@pytest.mark.asyncio
async def test_update_gate_manual_conflict_and_scheduled_skip(
    coord: ExecutionCoordinator, store: ExecutionStore
):
    coord.set_update_in_progress()

    manual = await coord.submit_manual(_manual_payload())
    assert manual.accepted is False
    assert manual.conflict is not None
    assert manual.conflict.code == "update_in_progress"
    assert "更新" in manual.conflict.message

    scheduled = await coord.submit_scheduled(_scheduled(), origin="in_app")
    assert scheduled.accepted is False
    assert scheduled.skip_status == "skipped_update_in_progress"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "skipped_update_in_progress"


@pytest.mark.asyncio
async def test_manual_success_writes_origin_manual(
    coord: ExecutionCoordinator, store: ExecutionStore, worker
):
    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    assert result.run_id is not None
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].origin == "manual"
    assert rows[0].task_name == MANUAL_TASK_NAME
    assert rows[0].task_id is None
    assert rows[0].status == "success"
    assert rows[0].finished_at is not None
    worker.tasks.start.assert_called_once()
    assert coord.active_run() is None


@pytest.mark.asyncio
async def test_native_late_missed_deadline(
    coord: ExecutionCoordinator, store: ExecutionStore, monkeypatch
):
    now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    occurrence = now - timedelta(minutes=20)

    monkeypatch.setattr(
        "services.execution_coordinator._local_now",
        lambda: now.astimezone(),
    )
    monkeypatch.setattr(
        "services.execution_coordinator._utc_now",
        lambda: now,
    )
    monkeypatch.setattr(
        "services.execution_coordinator.compute_occurrence",
        lambda trigger, n: occurrence,
    )

    result = await coord.submit_scheduled(_scheduled(), origin="native")
    assert result.accepted is False
    assert result.skip_status == "missed_deadline"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "missed_deadline"
    assert rows[0].origin == "native"
    assert rows[0].finished_at is not None
    result2 = await coord.submit_scheduled(_scheduled(), origin="native")
    assert result2.skip_status == "missed_deadline"
    assert len(store.list()) == 2


@pytest.mark.asyncio
async def test_stop_active_calls_worker_stop(
    coord: ExecutionCoordinator, state: AppState, worker
):
    assert await coord.stop_active() is False
    worker.tasks.stop.assert_not_called()

    state.active_run = ActiveRun(
        run_id="r1", origin="manual", task_name=MANUAL_TASK_NAME, occurrence_id=None
    )
    assert await coord.stop_active() is True
    worker.tasks.stop.assert_called_once()


@pytest.mark.asyncio
async def test_in_app_success_path(
    coord: ExecutionCoordinator, store: ExecutionStore, monkeypatch
):
    fixed = datetime(2026, 7, 19, 9, 2, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "services.execution_coordinator._local_now",
        lambda: fixed.astimezone(),
    )
    monkeypatch.setattr(
        "services.execution_coordinator._utc_now",
        lambda: fixed,
    )
    monkeypatch.setattr(
        "services.execution_coordinator.compute_occurrence",
        lambda trigger, now: fixed.replace(minute=0, second=0, microsecond=0),
    )
    result = await coord.submit_scheduled(_scheduled(), origin="in_app")
    assert result.accepted is True
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].origin == "in_app"
    assert rows[0].status == "success"
    assert rows[0].occurrence_id is not None
    assert coord.active_run() is None
