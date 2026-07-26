"""Unit tests for SchedulerManager callback runtime and delete order."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    ScheduledTask,
    ScheduledTaskCreate,
)
import scheduler_manager as sm
from scheduler_job_codec import SchedulerJobDecodeError, encode_execution_kwargs
from scheduler_manager import (
    SchedulerManager,
    _bind_callback_runtime,
    _clear_callback_runtime,
    scheduled_job_fired,
)


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


def _state(coordinator=None) -> SimpleNamespace:
    return SimpleNamespace(
        worker=None,
        execution_coordinator=coordinator,
        scheduler_manager=None,
    )


@pytest.fixture
async def manager(tmp_path: Path):
    state = _state()
    m = SchedulerManager(state, tmp_path / "jobs.sqlite", system_scheduler=None)
    await m.initialize(paused=True)
    yield m
    await m.shutdown()


# ---------------------------------------------------------------------------
# scheduled_job_fired — kwargs 解码 + 规范 state 绑定
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduled_job_fired_skips_wakeup_task():
    coordinator = SimpleNamespace(submit_scheduled=AsyncMock())
    state = _state(coordinator)
    _bind_callback_runtime(state)
    try:
        kwargs = encode_execution_kwargs(
            task_id="task-1",
            task_name="n",
            task_description="",
            task_list=["Main"],
            task_options={},
            pre_tasks=[],
            controller_name=None,
            device=None,
            resource_name=None,
            wakeup_enabled=True,
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        )
        await scheduled_job_fired(**kwargs)
    finally:
        _clear_callback_runtime()

    coordinator.submit_scheduled.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_job_fired_dispatches_non_wakeup_task():
    coordinator = SimpleNamespace(submit_scheduled=AsyncMock())
    state = _state(coordinator)
    _bind_callback_runtime(state)
    try:
        kwargs = encode_execution_kwargs(
            task_id="task-1",
            task_name="n",
            task_description="",
            task_list=["Main"],
            task_options={},
            pre_tasks=[],
            controller_name=None,
            device=None,
            resource_name=None,
            wakeup_enabled=False,
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        )
        await scheduled_job_fired(**kwargs)
    finally:
        _clear_callback_runtime()

    coordinator.submit_scheduled.assert_awaited_once()
    args, kwargs = coordinator.submit_scheduled.await_args
    assert args[0].id == "task-1"
    assert kwargs.get("origin") == "in_app" or (len(args) > 1 and args[1] == "in_app")


@pytest.mark.asyncio
async def test_scheduled_job_fired_uses_canonical_bound_state():
    """回调只读模块级绑定的规范 state，不 import main。"""
    coordinator = SimpleNamespace(submit_scheduled=AsyncMock())
    state = _state(coordinator)
    _bind_callback_runtime(state)
    try:
        assert sm._callback_runtime_state is state
        kwargs = encode_execution_kwargs(
            task_id="canon-1",
            task_name="canon",
            task_description="",
            task_list=["Main"],
            task_options={},
            pre_tasks=[],
            controller_name=None,
            device=None,
            resource_name=None,
            wakeup_enabled=False,
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        )
        await scheduled_job_fired(**kwargs)
    finally:
        _clear_callback_runtime()

    coordinator.submit_scheduled.assert_awaited_once()
    assert sm._callback_runtime_state is None


@pytest.mark.asyncio
async def test_manager_binds_and_clears_callback_runtime(tmp_path: Path):
    state = _state()
    m = SchedulerManager(state, tmp_path / "bind.sqlite")
    assert sm._callback_runtime_state is state
    await m.initialize(paused=True)
    assert sm._callback_runtime_state is state
    await m.shutdown()
    assert sm._callback_runtime_state is None


@pytest.mark.asyncio
async def test_due_date_trigger_dispatches_once_despite_job_removal(tmp_path: Path):
    """DateTrigger 到期后 APS 会先删 job；回调必须靠 kwargs 仍能派发一次。"""
    coordinator = SimpleNamespace(submit_scheduled=AsyncMock())
    state = _state(coordinator)
    m = SchedulerManager(state, tmp_path / "date.sqlite")
    await m.initialize(paused=True)

    run_date = datetime.now(timezone.utc) - timedelta(seconds=2)
    created = await m.create_task(
        ScheduledTaskCreate(
            name="once",
            enabled=True,
            wakeup_enabled=False,
            trigger_config=DateTriggerConfig(run_date=run_date),
            task_list=["Main"],
            task_options={},
            preTasks=[],
        )
    )
    job = m.scheduler.get_job(created.id)
    assert job is not None
    job_kwargs = dict(job.kwargs or {})

    # 模拟 APS 在回调前移除已到期的 DateTrigger job
    m.scheduler.remove_job(created.id)
    assert m.scheduler.get_job(created.id) is None

    await scheduled_job_fired(**job_kwargs)

    coordinator.submit_scheduled.assert_awaited_once()
    submitted = coordinator.submit_scheduled.await_args.args[0]
    assert submitted.id == created.id
    assert submitted.name == "once"
    assert isinstance(submitted.trigger_config, DateTriggerConfig)

    await m.shutdown()


@pytest.mark.asyncio
async def test_live_due_date_trigger_fires_via_scheduler(tmp_path: Path):
    """真实 APS 到期：job 被移除后仍通过 kwargs 派发一次。"""
    coordinator = SimpleNamespace(submit_scheduled=AsyncMock())
    state = _state(coordinator)
    m = SchedulerManager(state, tmp_path / "live_date.sqlite")
    await m.initialize(paused=False)

    run_date = datetime.now(timezone.utc) - timedelta(seconds=1)
    created = await m.create_task(
        ScheduledTaskCreate(
            name="live-once",
            enabled=True,
            wakeup_enabled=False,
            trigger_config=DateTriggerConfig(run_date=run_date),
            task_list=["Main"],
            task_options={},
            preTasks=[],
        )
    )

    # 等待 APS 处理 due job（misfire_grace 内应提交）
    for _ in range(50):
        if coordinator.submit_scheduled.await_count >= 1:
            break
        await asyncio.sleep(0.05)

    assert coordinator.submit_scheduled.await_count == 1
    submitted = coordinator.submit_scheduled.await_args.args[0]
    assert submitted.id == created.id
    # DateTrigger 无下次触发后 job 应被移除
    assert m.scheduler.get_job(created.id) is None

    await m.shutdown()


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


@pytest.mark.asyncio
async def test_create_persists_trigger_config_in_kwargs(manager: SchedulerManager):
    created = await manager.create_task(_create(cron="15 8 * * 1"))
    job = manager.scheduler.get_job(created.id)
    assert job is not None
    assert job.kwargs["trigger_config"]["type"] == "cron"
    assert job.kwargs["trigger_config"]["cron"] == "15 8 * * 1"
    assert job.kwargs["wakeup_enabled"] is False
    # 全局可导入回调（SQLAlchemyJobStore 序列化要求）
    assert job.func is scheduled_job_fired or job.func_ref.endswith(
        "scheduled_job_fired"
    )


# ---------------------------------------------------------------------------
# Undecodable job — delete/pause/resume must not be blocked by decode failure
#
# A persisted job whose kwargs decode fine but whose APS trigger object does not
# is the "zombie" scenario: strict `_decode_job` reads `job.trigger` and raises
# (OrTrigger is not Cron/Date/Interval), while the lenient
# `decode_scheduled_task_from_kwargs` reads `kwargs["trigger_config"]` and
# succeeds — so `scheduled_job_fired` still dispatches the job. Before the fix
# this job was invisible (get_all_tasks skips it), undeletable, unpausable and
# unresumable, yet still firing.
# ---------------------------------------------------------------------------


def _persist_undecodable_job(
    manager: SchedulerManager, task_id: str = "undecodable-1"
) -> str:
    """Persist a job whose strict `_decode_job` raises but lenient decode succeeds.

    `OrTrigger` is a real, picklable APS trigger; `decode_trigger` only handles
    Cron/Date/Interval, so the strict path raises SchedulerJobDecodeError while
    kwargs carry a valid `trigger_config`, so `scheduled_job_fired` would still
    fire the job.
    """
    trigger_config = CronTriggerConfig(cron="0 9 * * *")
    kwargs = encode_execution_kwargs(
        task_id=task_id,
        task_name="undecodable",
        task_description="",
        task_list=["Main"],
        task_options={},
        pre_tasks=[],
        controller_name=None,
        device=None,
        resource_name=None,
        wakeup_enabled=False,
        trigger_config=trigger_config,
    )
    or_trigger = OrTrigger(
        [CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*")]
    )
    manager.scheduler.add_job(
        scheduled_job_fired, trigger=or_trigger, id=task_id, kwargs=kwargs
    )
    return task_id


@pytest.mark.asyncio
async def test_get_all_tasks_skips_undecodable_job(manager: SchedulerManager):
    """Regression guard: the read path must skip (not delete) undecodable jobs."""
    task_id = _persist_undecodable_job(manager)
    job = manager.scheduler.get_job(task_id)
    assert job is not None  # really persisted
    # sanity: the strict path really does reject this job
    with pytest.raises(SchedulerJobDecodeError):
        manager._decode_job(job)

    tasks = await manager.get_all_tasks()

    assert all(t.id != task_id for t in tasks)


@pytest.mark.asyncio
async def test_delete_task_succeeds_despite_decode_failure(manager: SchedulerManager):
    """Decode failure must not gate APS removal — formerly returned False (zombie)."""
    task_id = _persist_undecodable_job(manager)
    sys_sched = MagicMock()
    manager.set_system_scheduler(sys_sched)

    ok = await manager.delete_task(task_id)

    assert ok is True
    assert manager.scheduler.get_job(task_id) is None
    # Defensive native unregister — we cannot know whether a native entry exists.
    sys_sched.unregister.assert_called_once_with(task_id)


@pytest.mark.asyncio
async def test_pause_task_succeeds_despite_decode_failure(manager: SchedulerManager):
    """Decode failure must not gate pause — formerly returned False (zombie)."""
    task_id = _persist_undecodable_job(manager)
    sys_sched = MagicMock()
    manager.set_system_scheduler(sys_sched)

    ok = await manager.pause_task(task_id)

    assert ok is True
    assert manager.scheduler.get_job(task_id) is not None
    # A paused task must not be woken by the OS — defensive unregister.
    sys_sched.unregister.assert_called_once_with(task_id)


@pytest.mark.asyncio
async def test_resume_task_succeeds_without_native_register_on_decode_failure(
    manager: SchedulerManager,
):
    """Decode failure must not gate resume, and native wakeup must NOT be restored
    (wakeup_enabled is unknowable). Formerly returned False (zombie). Must not raise."""
    task_id = _persist_undecodable_job(manager)
    sys_sched = MagicMock()
    manager.set_system_scheduler(sys_sched)
    # Pause first so resume has observable state to act on.
    assert await manager.pause_task(task_id) is True
    sys_sched.reset_mock()  # isolate resume's native side-effects

    ok = await manager.resume_task(task_id)

    assert ok is True  # also proves no exception escaped
    assert manager.scheduler.get_job(task_id) is not None
    # Cannot know wakeup_enabled → safer to skip native registration entirely.
    sys_sched.register.assert_not_called()
