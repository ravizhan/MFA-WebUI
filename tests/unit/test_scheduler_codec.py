"""Focused tests for scheduler APS job encode/decode codec (Lane A)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    PreTaskCommand,
    ScheduledTaskDeviceConfig,
)
from scheduler_job_codec import (
    SchedulerJobDecodeError,
    build_trigger,
    compute_occurrence,
    decode_job_to_scheduled_task,
    decode_pre_tasks_from_job_kwargs,
    decode_trigger,
    encode_execution_kwargs,
)
from services.native_cron import aps_dow_to_unix, unix_dow_to_aps


CANONICAL_PRE = [
    {"id": "canon-1", "command": "echo canonical", "enabled": True, "timeout": 30}
]

LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def _identity_normalize(task_list, task_options, pre_tasks):
    return list(task_list or []), dict(task_options or {}), list(pre_tasks or [])


# ---------------------------------------------------------------------------
# Trigger encode → decode round-trips
# ---------------------------------------------------------------------------


def test_cron_trigger_round_trip_no_dow():
    cfg = CronTriggerConfig(cron="0 9 * * *")
    trigger = build_trigger(cfg)
    assert isinstance(trigger, CronTrigger)
    ttype, decoded = decode_trigger(trigger)
    assert ttype == "cron"
    assert isinstance(decoded, CronTriggerConfig)
    assert decoded.cron == "0 9 * * *"


def test_cron_trigger_round_trip_with_dow_unix_mapping():
    """Unix DOW 1 (Monday) must map to APS 0 and back."""
    cfg = CronTriggerConfig(cron="0 12 * * 1")
    trigger = build_trigger(cfg)
    assert isinstance(trigger, CronTrigger)
    field_map = {f.name: str(f) for f in trigger.fields}
    assert field_map["day_of_week"] == str(unix_dow_to_aps(1))  # APS Monday = 0

    ttype, decoded = decode_trigger(trigger)
    assert ttype == "cron"
    assert isinstance(decoded, CronTriggerConfig)
    assert decoded.cron == "0 12 * * 1"


def test_cron_trigger_round_trip_sunday_unix_zero():
    """Unix DOW 0 (Sunday) ↔ APS 6."""
    cfg = CronTriggerConfig(cron="0 12 * * 0")
    trigger = build_trigger(cfg)
    assert isinstance(trigger, CronTrigger)
    field_map = {f.name: str(f) for f in trigger.fields}
    assert field_map["day_of_week"] == str(unix_dow_to_aps(0))  # 6
    _, decoded = decode_trigger(trigger)
    assert isinstance(decoded, CronTriggerConfig)
    assert decoded.cron == "0 12 * * 0"
    assert aps_dow_to_unix(int(field_map["day_of_week"])) == 0


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


# ---------------------------------------------------------------------------
# encode_execution_kwargs
# ---------------------------------------------------------------------------


def test_encode_execution_kwargs_pre_tasks_key_round_trip():
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
        task_list=["Main"],
        task_options={"Main": {"opt": "v"}},
        pre_tasks=[pt],
        controller_name="ADB",
        device=device,
        resource_name="Official",
        wakeup_enabled=False,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
    )
    assert "pre_tasks" in kwargs
    assert "preTasks" not in kwargs
    assert kwargs["pre_tasks"][0]["command"] == "echo hi"
    assert kwargs["wakeup_enabled"] is False

    # decode path only reads pre_tasks
    assert decode_pre_tasks_from_job_kwargs(kwargs) == kwargs["pre_tasks"]
    assert decode_pre_tasks_from_job_kwargs({"preTasks": CANONICAL_PRE}) == []
    assert decode_pre_tasks_from_job_kwargs({}) == []


def test_encode_execution_kwargs_wakeup_non_cron_raises():
    with pytest.raises(ValueError, match="wakeup_enabled"):
        encode_execution_kwargs(
            task_id="t",
            task_name="n",
            task_description=None,
            task_list=[],
            task_options={},
            pre_tasks=[],
            controller_name=None,
            device=None,
            resource_name=None,
            wakeup_enabled=True,
            trigger_config=DateTriggerConfig(
                run_date=datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)
            ),
        )


def test_encode_execution_kwargs_wakeup_interval_raises():
    with pytest.raises(ValueError, match="wakeup_enabled"):
        encode_execution_kwargs(
            task_id="t",
            task_name="n",
            task_description=None,
            task_list=[],
            task_options={},
            pre_tasks=[],
            controller_name=None,
            device=None,
            resource_name=None,
            wakeup_enabled=True,
            trigger_config=IntervalTriggerConfig(hours=1),
        )


def test_encode_execution_kwargs_wakeup_cron_ok():
    kwargs = encode_execution_kwargs(
        task_id="t",
        task_name="n",
        task_description=None,
        task_list=[],
        task_options={},
        pre_tasks=[],
        controller_name=None,
        device=None,
        resource_name=None,
        wakeup_enabled=True,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
    )
    assert kwargs["wakeup_enabled"] is True


def test_decode_job_to_scheduled_task_no_trigger_type_field():
    kwargs = encode_execution_kwargs(
        task_id="job-1",
        task_name="full",
        task_description="d",
        task_list=["Main"],
        task_options={"Main": {}},
        pre_tasks=CANONICAL_PRE,
        controller_name="ADB",
        device={
            "controller_name": "ADB",
            "device_type": "Adb",
            "device_address": "127.0.0.1:5555",
        },
        resource_name="Official",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
    )
    job = SimpleNamespace(
        id="job-1",
        kwargs=kwargs,
        trigger=build_trigger(CronTriggerConfig(cron="0 9 * * *")),
        next_run_time=datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc),
    )
    task = decode_job_to_scheduled_task(job, normalize=_identity_normalize)
    assert task.id == "job-1"
    assert not hasattr(task, "trigger_type") or "trigger_type" not in task.model_fields_set
    assert isinstance(task.trigger_config, CronTriggerConfig)
    assert task.trigger_config.cron == "0 9 * * *"
    assert task.wakeup_enabled is False
    assert len(task.preTasks) == 1


def test_decode_job_corrupt_trigger_raises():
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
    with pytest.raises(SchedulerJobDecodeError, match="trigger decode failed"):
        decode_job_to_scheduled_task(job, normalize=_identity_normalize)


# ---------------------------------------------------------------------------
# compute_occurrence
# ---------------------------------------------------------------------------


def test_compute_occurrence_cron_after_fire():
    """At 09:05 local, daily 09:00 → same day 09:00."""
    cfg = CronTriggerConfig(cron="0 9 * * *")
    now = datetime(2026, 7, 19, 9, 5, 0, tzinfo=LOCAL_TZ)
    occ = compute_occurrence(cfg, now)
    assert occ == datetime(2026, 7, 19, 9, 0, 0, tzinfo=LOCAL_TZ)


def test_compute_occurrence_cron_before_fire():
    """At 08:55 local, daily 09:00 → previous day 09:00."""
    cfg = CronTriggerConfig(cron="0 9 * * *")
    now = datetime(2026, 7, 19, 8, 55, 0, tzinfo=LOCAL_TZ)
    occ = compute_occurrence(cfg, now)
    assert occ == datetime(2026, 7, 18, 9, 0, 0, tzinfo=LOCAL_TZ)


def test_compute_occurrence_date_returns_run_date():
    run_date = datetime(2026, 7, 20, 15, 30, tzinfo=LOCAL_TZ)
    cfg = DateTriggerConfig(run_date=run_date)
    now = datetime(2026, 7, 19, 12, 0, tzinfo=LOCAL_TZ)
    assert compute_occurrence(cfg, now) == run_date


def test_compute_occurrence_interval_truncates_to_minute():
    cfg = IntervalTriggerConfig(hours=1)
    now = datetime(2026, 7, 19, 12, 34, 56, 789000, tzinfo=LOCAL_TZ)
    occ = compute_occurrence(cfg, now)
    assert occ == datetime(2026, 7, 19, 12, 34, 0, tzinfo=LOCAL_TZ)
