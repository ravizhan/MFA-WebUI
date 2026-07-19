"""Unit tests for SchedulerManager single-trigger ownership and delete order."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import CronTriggerConfig, ScheduledTask, ScheduledTaskCreate
from scheduler_manager import SchedulerManager, scheduled_job_fired


def _create(
    *,
    name: str = "t",
    enabled: bool = True,
    wakeup_enabled: bool = False,
    cron: str = "0 9 * * *",
) -> ScheduledTaskCreate:
    return ScheduledTaskCreate(
        name=name,
        enabled=enabled,
        wakeup_enabled=wakeup_enabled,
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
        task_options={},
        preTasks=[],
    )


def _task(
    task_id: str = "task-1",
    *,
    wakeup_enabled: bool = False,
    enabled: bool = True,
) -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name="n",
        enabled=enabled,
        wakeup_enabled=wakeup_enabled,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
    )


@pytest.fixture
async def manager(tmp_path: Path):
    m = SchedulerManager(tmp_path / "jobs.sqlite", system_scheduler=None)
    await m.initialize(paused=True)
    yield m
    await m.shutdown()


# ---------------------------------------------------------------------------
# scheduled_job_fired — single trigger authority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_job_fired_skips_wakeup_task(main_module):
    task = _task(wakeup_enabled=True)
    coordinator = SimpleNamespace(submit_scheduled=AsyncMock())
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    app_state = SimpleNamespace(
        execution_coordinator=coordinator,
        scheduler_manager=manager,
    )
    with patch.object(main_module, "app_state", app_state, create=True):
        await scheduled_job_fired(task_id=task.id)

    coordinator.submit_scheduled.assert_not_awaited()
    manager.get_task.assert_awaited_once_with(task.id)


@pytest.mark.asyncio
async def test_scheduled_job_fired_dispatches_non_wakeup_task(main_module):
    task = _task(wakeup_enabled=False)
    coordinator = SimpleNamespace(submit_scheduled=AsyncMock())
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    app_state = SimpleNamespace(
        execution_coordinator=coordinator,
        scheduler_manager=manager,
    )
    with patch.object(main_module, "app_state", app_state, create=True):
        await scheduled_job_fired(task_id=task.id)

    coordinator.submit_scheduled.assert_awaited_once()
    args, kwargs = coordinator.submit_scheduled.await_args
    assert args[0].id == task.id
    assert kwargs.get("origin") == "in_app" or (len(args) > 1 and args[1] == "in_app")


# ---------------------------------------------------------------------------
# delete_task — native only when desired; native-first for enabled wakeup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("wakeup_enabled", "enabled"),
    [
        (False, True),  # plain task: desired_wakeup false
        (True, False),  # paused wakeup: desired_wakeup false
    ],
)
async def test_delete_when_desired_wakeup_false_skips_native(
    manager: SchedulerManager, wakeup_enabled: bool, enabled: bool
):
    sys_sched = MagicMock()
    manager.set_system_scheduler(sys_sched)
    created = await manager.create_task(
        _create(wakeup_enabled=wakeup_enabled, enabled=enabled)
    )
    sys_sched.reset_mock()

    ok = await manager.delete_task(created.id)

    assert ok is True
    assert manager.scheduler.get_job(created.id) is None
    sys_sched.unregister.assert_not_called()


@pytest.mark.asyncio
async def test_delete_enabled_wakeup_native_then_aps(manager: SchedulerManager):
    order: list[str] = []
    sys_sched = MagicMock()
    sys_sched.unregister.side_effect = lambda tid: order.append("native")
    manager.set_system_scheduler(sys_sched)

    created = await manager.create_task(_create(wakeup_enabled=True, enabled=True))
    assert sys_sched.register.called
    sys_sched.reset_mock()
    order.clear()

    original_remove = manager.scheduler.remove_job

    def tracked_remove(job_id: str):
        order.append("aps")
        return original_remove(job_id)

    manager.scheduler.remove_job = tracked_remove  # type: ignore[method-assign]

    ok = await manager.delete_task(created.id)

    assert ok is True
    assert order == ["native", "aps"]
    assert manager.scheduler.get_job(created.id) is None
    sys_sched.unregister.assert_called_once_with(created.id)


@pytest.mark.asyncio
async def test_delete_enabled_wakeup_native_fail_keeps_aps(manager: SchedulerManager):
    sys_sched = MagicMock()
    sys_sched.unregister.side_effect = RuntimeError("native missing")
    manager.set_system_scheduler(sys_sched)

    created = await manager.create_task(_create(wakeup_enabled=True, enabled=True))
    job_before = manager.scheduler.get_job(created.id)
    assert job_before is not None

    ok = await manager.delete_task(created.id)

    assert ok is False
    assert manager.scheduler.get_job(created.id) is not None
    sys_sched.unregister.assert_called_once_with(created.id)
