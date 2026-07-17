"""Focused tests for scheduler job kwargs pre_tasks encoding/execution."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.util import obj_to_ref

from models.scheduler import (
    CronTriggerConfig,
    PreTaskCommand,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from scheduler_job_codec import decode_pre_tasks_from_job_kwargs
from scheduler_manager import SchedulerManager, execute_scheduled_task

CANONICAL_PRE = [
    {"id": "canon-1", "command": "echo canonical", "enabled": True, "timeout": 30}
]


@pytest.fixture
async def manager(tmp_path):
    mgr = SchedulerManager()
    mgr._db_path = tmp_path / "scheduler.sqlite"
    await mgr.initialize(start_scheduler=True, paused=True)
    assert mgr.scheduler is not None
    try:
        yield mgr
    finally:
        await mgr.shutdown()


def _base_create(**overrides: Any) -> ScheduledTaskCreate:
    data: dict[str, Any] = {
        "name": "kwargs-task",
        "trigger_type": "cron",
        "trigger_config": CronTriggerConfig(cron="0 9 * * *"),
        "task_list": ["Main"],
        "enabled": False,
    }
    data.update(overrides)
    return ScheduledTaskCreate(**data)


def test_decode_pre_tasks_reads_only_pre_tasks_key():
    assert decode_pre_tasks_from_job_kwargs({"pre_tasks": []}) == []
    assert decode_pre_tasks_from_job_kwargs({"pre_tasks": CANONICAL_PRE}) == CANONICAL_PRE
    assert decode_pre_tasks_from_job_kwargs({}) == []
    # API-key-shaped junk in APS kwargs is ignored (not read)
    assert (
        decode_pre_tasks_from_job_kwargs(
            {"preTasks": [{"id": "x", "command": "echo x", "enabled": True, "timeout": 1}]}
        )
        == []
    )


@pytest.mark.asyncio
async def test_create_job_kwargs_use_pre_tasks(manager: SchedulerManager):
    task = await manager.create_task(_base_create())
    assert manager.scheduler is not None
    job = manager.scheduler.get_job(task.id)
    assert job is not None
    assert "pre_tasks" in job.kwargs
    assert "preTasks" not in job.kwargs
    assert job.func_ref == obj_to_ref(execute_scheduled_task)
    assert job.func_ref == "scheduler_manager:execute_scheduled_task"


@pytest.mark.asyncio
async def test_update_job_kwargs_use_pre_tasks(manager: SchedulerManager):
    task = await manager.create_task(_base_create())
    updated = await manager.update_task(
        task.id,
        ScheduledTaskUpdate(name="renamed"),
    )
    assert updated is not None
    assert manager.scheduler is not None
    job = manager.scheduler.get_job(task.id)
    assert job is not None
    assert "pre_tasks" in job.kwargs
    assert "preTasks" not in job.kwargs
    assert job.kwargs["task_name"] == "renamed"
    assert job.func_ref == "scheduler_manager:execute_scheduled_task"


@pytest.mark.asyncio
async def test_create_api_preTasks_encoded_as_aps_pre_tasks(manager: SchedulerManager):
    """API model field preTasks is encoded into APS kwargs pre_tasks."""
    pt = PreTaskCommand(id="pt-1", command="echo from-api", enabled=True, timeout=30)
    with patch.object(
        manager,
        "_normalize_task_payload",
        return_value=(["Main"], {"Main": {}}, [pt]),
    ):
        task = await manager.create_task(_base_create(preTasks=[pt]))
    assert manager.scheduler is not None
    job = manager.scheduler.get_job(task.id)
    assert job is not None
    assert "pre_tasks" in job.kwargs
    assert "preTasks" not in job.kwargs
    assert job.kwargs["pre_tasks"][0]["command"] == "echo from-api"


@pytest.mark.asyncio
async def test_get_task_decodes_pre_tasks_key(manager: SchedulerManager):
    from apscheduler.triggers.cron import CronTrigger

    task_id = "pre-tasks-job"
    assert manager.scheduler is not None
    manager.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*"),
        id=task_id,
        kwargs={
            "task_id": task_id,
            "task_name": "with-pre",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {"Main": {}},
            "pre_tasks": CANONICAL_PRE,
            "controller_name": None,
            "device": None,
            "resource_name": None,
            "wakeup_enabled": False,
        },
    )
    manager.scheduler.pause_job(task_id)

    with patch.object(
        manager,
        "_normalize_task_payload",
        wraps=manager._normalize_task_payload,
    ) as normalize:
        task = await manager.get_task(task_id)
        assert task is not None
        assert normalize.call_args.args[2] == CANONICAL_PRE


@pytest.mark.asyncio
async def test_execute_forwards_pre_tasks():
    captured: dict[str, Any] = {}

    async def _execute_task(**kwargs):
        captured.update(kwargs)

    mock_mgr = MagicMock()
    mock_mgr._execute_task = AsyncMock(side_effect=_execute_task)

    with patch("scheduler_manager._ACTIVE_MANAGER", mock_mgr):
        await execute_scheduled_task(
            task_id="t1",
            task_name="run",
            task_description="",
            task_list=["Main"],
            task_options={},
            pre_tasks=CANONICAL_PRE,
        )

    mock_mgr._execute_task.assert_awaited_once()
    assert captured["pre_tasks"] == CANONICAL_PRE


@pytest.mark.asyncio
async def test_execute_missing_pre_tasks_becomes_empty_list():
    captured: dict[str, Any] = {}

    async def _execute_task(**kwargs):
        captured.update(kwargs)

    mock_mgr = MagicMock()
    mock_mgr._execute_task = AsyncMock(side_effect=_execute_task)

    with patch("scheduler_manager._ACTIVE_MANAGER", mock_mgr):
        await execute_scheduled_task(
            task_id="t2",
            task_name="empty",
            task_description="",
            task_list=["Main"],
            task_options={},
        )

    assert captured["pre_tasks"] == []


@pytest.mark.asyncio
async def test_update_api_preTasks_writes_aps_pre_tasks(manager: SchedulerManager):
    """API model ScheduledTaskUpdate.preTasks → APS kwargs pre_tasks."""
    pt = PreTaskCommand(id="pt-1", command="echo hi", enabled=True, timeout=30)
    task = await manager.create_task(_base_create())

    with patch.object(
        manager,
        "_normalize_task_payload",
        return_value=(["Main"], {"Main": {}}, [pt]),
    ):
        updated = await manager.update_task(
            task.id,
            ScheduledTaskUpdate(preTasks=[pt]),
        )
    assert updated is not None
    assert manager.scheduler is not None
    job = manager.scheduler.get_job(task.id)
    assert job is not None
    assert "pre_tasks" in job.kwargs
    assert "preTasks" not in job.kwargs
    assert job.kwargs["pre_tasks"][0]["command"] == "echo hi"
