"""Focused tests for scheduler job kwargs pre_tasks / preTasks compatibility."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import obj_to_ref

from models.scheduler import (
    CronTriggerConfig,
    PreTaskCommand,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
)
from scheduler_job_codec import (
    decode_pre_tasks_from_job_kwargs,
    resolve_execute_pre_tasks,
)
from scheduler_manager import SchedulerManager, execute_scheduled_task

LEGACY_PRE = [{"id": "legacy-1", "command": "echo legacy", "enabled": True, "timeout": 30}]
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


def test_decode_prefers_canonical_including_empty_list():
    assert decode_pre_tasks_from_job_kwargs({"pre_tasks": []}) == []
    assert decode_pre_tasks_from_job_kwargs({"pre_tasks": [], "preTasks": LEGACY_PRE}) == []
    assert decode_pre_tasks_from_job_kwargs({"preTasks": LEGACY_PRE}) == LEGACY_PRE
    assert decode_pre_tasks_from_job_kwargs(
        {"pre_tasks": CANONICAL_PRE, "preTasks": LEGACY_PRE}
    ) == (CANONICAL_PRE)
    assert decode_pre_tasks_from_job_kwargs({}) == []


def test_resolve_execute_pre_tasks_preference():
    assert resolve_execute_pre_tasks([], LEGACY_PRE) == []
    assert resolve_execute_pre_tasks(None, LEGACY_PRE) == LEGACY_PRE
    assert resolve_execute_pre_tasks(CANONICAL_PRE, LEGACY_PRE) == CANONICAL_PRE
    assert resolve_execute_pre_tasks(None, None) == []


@pytest.mark.asyncio
async def test_create_job_kwargs_use_canonical_pre_tasks(manager: SchedulerManager):
    task = await manager.create_task(_base_create())
    assert manager.scheduler is not None
    job = manager.scheduler.get_job(task.id)
    assert job is not None
    assert "pre_tasks" in job.kwargs
    assert "preTasks" not in job.kwargs
    assert job.func_ref == obj_to_ref(execute_scheduled_task)
    assert job.func_ref == "scheduler_manager:execute_scheduled_task"


@pytest.mark.asyncio
async def test_update_job_kwargs_use_canonical_pre_tasks(manager: SchedulerManager):
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
async def test_update_legacy_job_rewrites_to_canonical_key(manager: SchedulerManager):
    """A job persisted with legacy preTasks is rewritten to pre_tasks on update."""
    task_id = "legacy-job-id"
    assert manager.scheduler is not None
    manager.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*"),
        id=task_id,
        kwargs={
            "task_id": task_id,
            "task_name": "legacy",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {"Main": {}},
            "preTasks": LEGACY_PRE,
            "controller_name": None,
            "device": None,
            "resource_name": None,
        },
    )
    manager.scheduler.pause_job(task_id)

    before = manager.scheduler.get_job(task_id)
    assert before is not None
    assert "preTasks" in before.kwargs
    assert "pre_tasks" not in before.kwargs

    updated = await manager.update_task(
        task_id,
        ScheduledTaskUpdate(name="migrated"),
    )
    assert updated is not None

    after = manager.scheduler.get_job(task_id)
    assert after is not None
    assert "pre_tasks" in after.kwargs
    assert "preTasks" not in after.kwargs
    assert after.kwargs["task_name"] == "migrated"
    assert after.func_ref == "scheduler_manager:execute_scheduled_task"


@pytest.mark.asyncio
async def test_get_task_prefers_canonical_empty_over_legacy(manager: SchedulerManager):
    task_id = "both-keys-job"
    assert manager.scheduler is not None
    manager.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*"),
        id=task_id,
        kwargs={
            "task_id": task_id,
            "task_name": "both",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {"Main": {}},
            "pre_tasks": [],
            "preTasks": LEGACY_PRE,
            "controller_name": None,
            "device": None,
            "resource_name": None,
        },
    )
    manager.scheduler.pause_job(task_id)

    # Without worker.interface, normalize returns empty pre_tasks; still must not
    # crash and must have preferred the canonical key during decode.
    with patch.object(
        manager,
        "_normalize_task_payload",
        wraps=manager._normalize_task_payload,
    ) as normalize:
        task = await manager.get_task(task_id)
        assert task is not None
        # Third positional arg is the decoded pre-tasks value.
        assert normalize.call_args.args[2] == []


@pytest.mark.asyncio
async def test_legacy_execute_invocation_forwards_preTasks():
    """Legacy persisted kwargs (preTasks=...) still reach the manager."""
    captured: dict[str, Any] = {}

    async def _execute_task(**kwargs):
        captured.update(kwargs)

    mock_mgr = MagicMock()
    mock_mgr._execute_task = AsyncMock(side_effect=_execute_task)

    with patch("scheduler_manager._ACTIVE_MANAGER", mock_mgr):
        await execute_scheduled_task(
            task_id="t1",
            task_name="legacy-run",
            task_description="",
            task_list=["Main"],
            task_options={},
            preTasks=LEGACY_PRE,
        )

    mock_mgr._execute_task.assert_awaited_once()
    assert captured["pre_tasks"] == LEGACY_PRE


@pytest.mark.asyncio
async def test_execute_canonical_empty_wins_over_legacy_nonempty():
    captured: dict[str, Any] = {}

    async def _execute_task(**kwargs):
        captured.update(kwargs)

    mock_mgr = MagicMock()
    mock_mgr._execute_task = AsyncMock(side_effect=_execute_task)

    with patch("scheduler_manager._ACTIVE_MANAGER", mock_mgr):
        await execute_scheduled_task(
            task_id="t2",
            task_name="empty-wins",
            task_description="",
            task_list=["Main"],
            task_options={},
            pre_tasks=[],
            preTasks=LEGACY_PRE,
        )

    assert captured["pre_tasks"] == []


@pytest.mark.asyncio
async def test_update_preserves_pre_tasks_content_when_rewriting(manager: SchedulerManager):
    """When worker normalizes pre-tasks, update still writes the canonical key."""
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
