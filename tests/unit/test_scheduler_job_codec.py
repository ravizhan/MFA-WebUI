"""Focused tests for scheduler APS job encode/decode codec."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    PreTaskCommand,
    ScheduledTaskCreate,
    ScheduledTaskDeviceConfig,
    ScheduledTaskUpdate,
)
from scheduler_job_codec import (
    SchedulerJobDecodeError,
    build_trigger,
    decode_job_to_scheduled_task,
    decode_pre_tasks_from_job_kwargs,
    decode_trigger,
    encode_execution_kwargs,
)
from scheduler_manager import SchedulerManager

CANONICAL_PRE = [
    {"id": "canon-1", "command": "echo canonical", "enabled": True, "timeout": 30}
]


def _identity_normalize(task_list, task_options, pre_tasks):
    return list(task_list or []), dict(task_options or {}), list(pre_tasks or [])


# ---------------------------------------------------------------------------
# Pure codec: triggers
# ---------------------------------------------------------------------------


def test_cron_trigger_round_trip():
    cfg = CronTriggerConfig(cron="15 8 * * 1-5")
    trigger = build_trigger(cfg)
    assert isinstance(trigger, CronTrigger)
    ttype, decoded = decode_trigger(trigger)
    assert ttype == "cron"
    assert isinstance(decoded, CronTriggerConfig)
    assert decoded.cron == "15 8 * * 1-5"


def test_date_trigger_round_trip_timezone_aware():
    run_date = datetime(2026, 7, 17, 12, 30, tzinfo=timezone.utc)
    cfg = DateTriggerConfig(run_date=run_date)
    trigger = build_trigger(cfg)
    assert isinstance(trigger, DateTrigger)
    ttype, decoded = decode_trigger(trigger)
    assert ttype == "date"
    assert isinstance(decoded, DateTriggerConfig)
    assert decoded.run_date == run_date
    assert decoded.run_date.tzinfo is not None


def test_interval_trigger_round_trip_with_bounds():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    cfg = IntervalTriggerConfig(
        weeks=1,
        days=2,
        hours=3,
        minutes=4,
        seconds=5,
        start_date=start,
        end_date=end,
    )
    trigger = build_trigger(cfg)
    assert isinstance(trigger, IntervalTrigger)
    ttype, decoded = decode_trigger(trigger)
    assert ttype == "interval"
    assert isinstance(decoded, IntervalTriggerConfig)
    assert decoded.weeks == 1
    assert decoded.days == 2
    assert decoded.hours == 3
    assert decoded.minutes == 4
    assert decoded.seconds == 5
    assert decoded.start_date is not None
    assert decoded.end_date is not None


def test_decode_unknown_trigger_raises():
    with pytest.raises(ValueError, match="未知的触发器类型"):
        decode_trigger(object())


def test_decode_date_missing_run_date_raises():
    trigger = DateTrigger(run_date=datetime(2026, 1, 1))
    trigger.run_date = None  # type: ignore[assignment]
    with pytest.raises(ValueError, match="run_date"):
        decode_trigger(trigger)


def test_decode_cron_missing_fields_raises_no_star_default():
    """Malformed CronTrigger must not invent '*' for absent named fields."""
    trigger = build_trigger(CronTriggerConfig(cron="0 9 * * *"))
    # Drop day_of_week from the field list so decode cannot fall back to '*'.
    trigger.fields = [f for f in trigger.fields if f.name != "day_of_week"]
    with pytest.raises(ValueError, match="missing required field") as ei:
        decode_trigger(trigger)
    assert "day_of_week" in str(ei.value)
    assert "* * * * *" not in str(ei.value)


def test_decode_cron_multiple_missing_fields_listed():
    trigger = build_trigger(CronTriggerConfig(cron="0 9 * * *"))
    trigger.fields = [f for f in trigger.fields if f.name in ("minute", "hour")]
    with pytest.raises(ValueError, match="missing required field") as ei:
        decode_trigger(trigger)
    msg = str(ei.value)
    assert "day" in msg
    assert "month" in msg
    assert "day_of_week" in msg


# ---------------------------------------------------------------------------
# Pure codec: kwargs / pre-tasks
# ---------------------------------------------------------------------------


def test_decode_pre_tasks_reads_only_pre_tasks_key():
    assert decode_pre_tasks_from_job_kwargs({"pre_tasks": []}) == []
    assert decode_pre_tasks_from_job_kwargs({"pre_tasks": CANONICAL_PRE}) == CANONICAL_PRE
    assert decode_pre_tasks_from_job_kwargs({}) == []
    assert (
        decode_pre_tasks_from_job_kwargs(
            {"preTasks": [{"id": "x", "command": "echo x", "enabled": True, "timeout": 1}]}
        )
        == []
    )


def test_encode_execution_kwargs_schema_and_fields():
    device = ScheduledTaskDeviceConfig(
        controller_name="ADB",
        device_type="Adb",
        device_address="127.0.0.1:5555",
    )
    pt = PreTaskCommand(id="pt-1", command="echo hi", enabled=True, timeout=30)
    kwargs = encode_execution_kwargs(
        task_id="tid-1",
        task_name="name",
        task_description="desc",
        task_list=["Main", "Side"],
        task_options={"Main": {"opt": "v"}},
        pre_tasks=[pt],
        controller_name="ADB",
        device=device,
        resource_name="Official",
    )
    assert set(kwargs.keys()) == {
        "task_id",
        "task_name",
        "task_description",
        "task_list",
        "task_options",
        "pre_tasks",
        "controller_name",
        "device",
        "resource_name",
        "wakeup_enabled",
    }
    assert "preTasks" not in kwargs
    assert kwargs["pre_tasks"][0]["command"] == "echo hi"
    assert kwargs["device"]["device_address"] == "127.0.0.1:5555"
    assert kwargs["resource_name"] == "Official"
    assert kwargs["task_options"] == {"Main": {"opt": "v"}}
    assert kwargs["wakeup_enabled"] is False


def test_decode_job_to_scheduled_task_full_payload():
    device = {
        "controller_name": "ADB",
        "device_type": "Adb",
        "device_address": "127.0.0.1:5555",
    }
    kwargs = encode_execution_kwargs(
        task_id="job-1",
        task_name="full",
        task_description="d",
        task_list=["Main"],
        task_options={"Main": {}},
        pre_tasks=CANONICAL_PRE,
        controller_name="ADB",
        device=device,
        resource_name="Official",
    )
    job = SimpleNamespace(
        id="job-1",
        kwargs=kwargs,
        trigger=build_trigger(CronTriggerConfig(cron="0 9 * * *")),
        next_run_time=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
    )
    task = decode_job_to_scheduled_task(job, normalize=_identity_normalize)
    assert task.id == "job-1"
    assert task.name == "full"
    assert task.trigger_type == "cron"
    assert isinstance(task.trigger_config, CronTriggerConfig)
    assert task.trigger_config.cron == "0 9 * * *"
    assert task.task_list == ["Main"]
    assert len(task.preTasks) == 1
    assert task.preTasks[0].command == "echo canonical"
    assert task.device is not None
    assert task.device.device_address == "127.0.0.1:5555"
    assert task.resource_name == "Official"
    assert task.enabled is True


def test_decode_job_missing_pre_tasks_defaults_empty():
    job = SimpleNamespace(
        id="no-pre",
        kwargs={
            "task_name": "L",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
        },
        trigger=build_trigger(CronTriggerConfig(cron="0 1 * * *")),
        next_run_time=None,
    )
    task = decode_job_to_scheduled_task(job, normalize=_identity_normalize)
    assert task.preTasks == []
    assert task.enabled is False


def test_decode_job_corrupt_trigger_raises_without_default_cron():
    job = SimpleNamespace(
        id="bad",
        kwargs={
            "task_name": "bad",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
        },
        trigger=object(),
        next_run_time=None,
    )
    with pytest.raises(SchedulerJobDecodeError, match="trigger decode failed") as ei:
        decode_job_to_scheduled_task(job, normalize=_identity_normalize)
    assert ei.value.job_id == "bad"
    assert "* * * * *" not in str(ei.value)


def test_decode_job_preserves_empty_task_description_string():
    """Empty persisted description must remain '', not become None."""
    job = SimpleNamespace(
        id="desc-empty",
        kwargs={
            "task_name": "n",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
        },
        trigger=build_trigger(CronTriggerConfig(cron="0 1 * * *")),
        next_run_time=None,
    )
    task = decode_job_to_scheduled_task(job, normalize=_identity_normalize)
    assert task.description == ""
    assert task.description is not None


def test_decode_job_malformed_cron_fields_raises_scheduler_error():
    trigger = build_trigger(CronTriggerConfig(cron="0 9 * * *"))
    trigger.fields = [f for f in trigger.fields if f.name != "hour"]
    job = SimpleNamespace(
        id="malformed-cron",
        kwargs={
            "task_name": "m",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
        },
        trigger=trigger,
        next_run_time=None,
    )
    with pytest.raises(SchedulerJobDecodeError, match="hour") as ei:
        decode_job_to_scheduled_task(job, normalize=_identity_normalize)
    assert ei.value.job_id == "malformed-cron"


# ---------------------------------------------------------------------------
# Manager integration via codec
# ---------------------------------------------------------------------------


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


def _create(**overrides: Any) -> ScheduledTaskCreate:
    data: dict[str, Any] = {
        "name": "codec-task",
        "trigger_type": "cron",
        "trigger_config": CronTriggerConfig(cron="0 9 * * *"),
        "task_list": ["Main"],
        "enabled": False,
        "controller_name": "ADB",
        "device": ScheduledTaskDeviceConfig(
            controller_name="ADB",
            device_type="Adb",
            device_address="127.0.0.1:5555",
        ),
        "resource_name": "Official",
    }
    data.update(overrides)
    return ScheduledTaskCreate(**data)


@pytest.mark.asyncio
async def test_create_and_update_share_identical_kwargs_schema(manager: SchedulerManager):
    task = await manager.create_task(_create(wakeup_enabled=True))
    assert manager.scheduler is not None
    created_job = manager.scheduler.get_job(task.id)
    assert created_job is not None
    create_keys = set(created_job.kwargs.keys())
    assert created_job.kwargs["wakeup_enabled"] is True

    updated = await manager.update_task(task.id, ScheduledTaskUpdate(name="renamed"))
    assert updated is not None
    updated_job = manager.scheduler.get_job(task.id)
    assert updated_job is not None
    update_keys = set(updated_job.kwargs.keys())

    assert create_keys == update_keys
    assert "pre_tasks" in create_keys
    assert "preTasks" not in create_keys
    assert updated_job.kwargs["task_name"] == "renamed"
    # Omitted update fields must preserve wakeup_enabled.
    assert updated.wakeup_enabled is True
    assert updated_job.kwargs["wakeup_enabled"] is True
    assert created_job.func_ref == "scheduler_manager:execute_scheduled_task"
    assert updated_job.func_ref == "scheduler_manager:execute_scheduled_task"


@pytest.mark.asyncio
async def test_get_and_list_share_decode_path(manager: SchedulerManager):
    task = await manager.create_task(_create(name="shared-decode"))
    one = await manager.get_task(task.id)
    all_tasks = await manager.get_all_tasks()
    assert one is not None
    match = next(t for t in all_tasks if t.id == task.id)
    assert one.model_dump(exclude={"created_at", "updated_at"}) == match.model_dump(
        exclude={"created_at", "updated_at"}
    )
    assert one.resource_name == "Official"
    assert one.device is not None
    assert one.device.device_address == "127.0.0.1:5555"


@pytest.mark.asyncio
async def test_get_list_update_corrupt_trigger_visible_no_mutation(
    manager: SchedulerManager,
):
    task = await manager.create_task(_create(name="corrupt-me"))
    assert manager.scheduler is not None
    job = manager.scheduler.get_job(task.id)
    assert job is not None
    before_kwargs = dict(job.kwargs)
    before_func = job.func_ref

    corrupt_job = SimpleNamespace(
        id=task.id,
        kwargs=before_kwargs,
        trigger=object(),
        next_run_time=None,
        func_ref=before_func,
    )

    real_get_job = manager.scheduler.get_job

    def fake_get_job(job_id, *a, **k):
        if job_id == task.id:
            return corrupt_job
        return real_get_job(job_id, *a, **k)

    def fake_get_jobs(*a, **k):
        return [corrupt_job]

    with patch.object(manager.scheduler, "get_job", side_effect=fake_get_job):
        with pytest.raises(SchedulerJobDecodeError, match="trigger decode failed"):
            await manager.get_task(task.id)

    with patch.object(manager.scheduler, "get_jobs", side_effect=fake_get_jobs):
        with pytest.raises(SchedulerJobDecodeError, match="trigger decode failed"):
            await manager.get_all_tasks()

    # update without new trigger_config must raise and not call modify_job
    with (
        patch.object(manager.scheduler, "get_job", side_effect=fake_get_job),
        patch.object(manager.scheduler, "modify_job") as modify_job,
    ):
        with pytest.raises(SchedulerJobDecodeError, match="trigger decode failed"):
            await manager.update_task(task.id, ScheduledTaskUpdate(name="nope"))
        modify_job.assert_not_called()

    # Original persisted job still intact
    restored = real_get_job(task.id)
    assert restored is not None
    assert restored.kwargs == before_kwargs
    assert restored.func_ref == before_func
    assert isinstance(restored.trigger, CronTrigger)


@pytest.mark.asyncio
async def test_malformed_cron_fields_manager_decode_no_mutation(
    manager: SchedulerManager,
):
    """Manager get/list raise on missing CronTrigger fields without mutating store."""
    task = await manager.create_task(_create(name="malformed-cron-mgr"))
    assert manager.scheduler is not None
    real_get_job = manager.scheduler.get_job
    real_job = real_get_job(task.id)
    assert real_job is not None
    before_kwargs = dict(real_job.kwargs)
    before_func = real_job.func_ref

    broken = build_trigger(CronTriggerConfig(cron="0 9 * * *"))
    broken.fields = [f for f in broken.fields if f.name != "month"]
    corrupt_job = SimpleNamespace(
        id=task.id,
        kwargs=before_kwargs,
        trigger=broken,
        next_run_time=real_job.next_run_time,
        func_ref=before_func,
    )

    def fake_get_job(job_id, *a, **k):
        if job_id == task.id:
            return corrupt_job
        return real_get_job(job_id, *a, **k)

    with patch.object(manager.scheduler, "get_job", side_effect=fake_get_job):
        with pytest.raises(SchedulerJobDecodeError, match="month"):
            await manager.get_task(task.id)

    with patch.object(manager.scheduler, "get_jobs", return_value=[corrupt_job]):
        with pytest.raises(SchedulerJobDecodeError, match="month"):
            await manager.get_all_tasks()

    restored = real_get_job(task.id)
    assert restored is not None
    assert restored.kwargs == before_kwargs
    assert restored.func_ref == before_func
    assert isinstance(restored.trigger, CronTrigger)

    # create path still surfaces empty description as '' (not None)
    assert task.description == ""


@pytest.mark.asyncio
async def test_update_with_new_trigger_skips_corrupt_old_trigger(
    manager: SchedulerManager,
):
    """When caller supplies trigger_config, old corrupt trigger is not required."""
    task = await manager.create_task(_create())
    assert manager.scheduler is not None
    real_get = manager.scheduler.get_job
    real_job = real_get(task.id)
    assert real_job is not None

    corrupt = SimpleNamespace(
        id=task.id,
        kwargs=dict(real_job.kwargs),
        trigger=object(),
        next_run_time=None,
    )
    call_count = {"n": 0}

    def get_job_side_effect(job_id, *a, **k):
        call_count["n"] += 1
        # First lookup in update_task sees corrupt job; later get_task uses store.
        if call_count["n"] == 1:
            return corrupt
        return real_get(job_id)

    with patch.object(manager.scheduler, "get_job", side_effect=get_job_side_effect):
        updated = await manager.update_task(
            task.id,
            ScheduledTaskUpdate(
                trigger_type="cron",
                trigger_config=CronTriggerConfig(cron="30 10 * * *"),
            ),
        )
    assert updated is not None
    assert isinstance(updated.trigger_config, CronTriggerConfig)
    assert updated.trigger_config.cron == "30 10 * * *"
    final = real_get(task.id)
    assert final is not None
    assert isinstance(final.trigger, CronTrigger)
