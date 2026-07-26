"""Focused tests for scheduler APS job encode/decode codec."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger
from pydantic import ValidationError

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
    decode_scheduled_task_from_kwargs,
    decode_trigger,
    encode_execution_kwargs,
)
from services.native_cron import aps_dow_to_unix, unix_dow_to_aps


CANONICAL_PRE = [
    {"id": "canon-1", "command": "echo canonical", "enabled": True, "timeout": 30}
]

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def _identity_normalize(task_list, task_options, pre_tasks):
    return list(task_list or []), dict(task_options or {}), list(pre_tasks or [])


def _cron_fire_weekdays(cron: str, *, start: datetime, count: int = 14) -> list[str]:
    """收集 cron 触发日的英文星期缩写，用于语义对比。"""
    trigger = build_trigger(CronTriggerConfig(cron=cron), timezone=start.tzinfo)
    fires: list[str] = []
    last = None
    cursor = start
    for _ in range(count * 2):
        nxt = trigger.get_next_fire_time(last, cursor)
        if nxt is None:
            break
        fires.append(nxt.strftime("%a"))
        last = nxt
        cursor = nxt
        if len(fires) >= count:
            break
    return fires


# ---------------------------------------------------------------------------
# Trigger encode → decode round-trips
# ---------------------------------------------------------------------------


def test_cron_trigger_round_trip_no_dow():
    cfg = CronTriggerConfig(cron="0 9 * * *")
    trigger = build_trigger(cfg)
    ttype, decoded = decode_trigger(trigger)
    assert ttype == "cron"
    assert decoded.cron == "0 9 * * *"


def test_cron_trigger_round_trip_with_dow_unix_mapping():
    """Unix DOW 1 (Monday) must map to APS 0 and back."""
    cfg = CronTriggerConfig(cron="0 12 * * 1")
    trigger = build_trigger(cfg)
    field_map = {f.name: str(f) for f in trigger.fields}
    assert field_map["day_of_week"] == str(unix_dow_to_aps(1))  # APS Monday = 0

    ttype, decoded = decode_trigger(trigger)
    assert ttype == "cron"
    assert decoded.cron == "0 12 * * 1"


def test_cron_trigger_round_trip_sunday_unix_zero():
    """Unix DOW 0 (Sunday) ↔ APS 6."""
    cfg = CronTriggerConfig(cron="0 12 * * 0")
    trigger = build_trigger(cfg)
    field_map = {f.name: str(f) for f in trigger.fields}
    assert field_map["day_of_week"] == str(unix_dow_to_aps(0))  # 6
    _, decoded = decode_trigger(trigger)
    assert decoded.cron == "0 12 * * 0"
    assert aps_dow_to_unix(int(field_map["day_of_week"])) == 0


def test_date_trigger_round_trip_timezone_aware():
    run_date = datetime(2026, 7, 17, 12, 30, tzinfo=timezone.utc)
    cfg = DateTriggerConfig(run_date=run_date)
    trigger = build_trigger(cfg)
    ttype, decoded = decode_trigger(trigger)
    assert ttype == "date"
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
    ttype, decoded = decode_trigger(trigger)
    assert ttype == "interval"
    assert decoded.weeks == 1
    assert decoded.days == 2
    assert decoded.hours == 3
    assert decoded.minutes == 4
    assert decoded.seconds == 5
    assert decoded.start_date is not None
    assert decoded.end_date is not None


# ---------------------------------------------------------------------------
# IntervalTriggerConfig — zero-total validator
# ---------------------------------------------------------------------------


def test_interval_all_none_raises():
    """全 None 间隔（未指定任何字段）总时长为零，必须拒绝。"""
    with pytest.raises(ValidationError, match="间隔触发器总时长不能为零"):
        IntervalTriggerConfig()


def test_interval_all_zero_raises():
    """所有字段显式为零同样构成零间隔，必须拒绝。"""
    with pytest.raises(ValidationError, match="间隔触发器总时长不能为零"):
        IntervalTriggerConfig(weeks=0, days=0, hours=0, minutes=0, seconds=0)


def test_interval_single_field_valid():
    """仅设置一个字段、其余 None 是合法用法。"""
    cfg = IntervalTriggerConfig(minutes=5)
    assert cfg.minutes == 5
    assert cfg.weeks is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"hours": 1, "minutes": 0, "seconds": 0},
        {"weeks": 0, "days": 1},
        {"seconds": 30},
    ],
)
def test_interval_partial_zero_total_nonzero_valid(kwargs):
    """单个字段为 0 合法，只要总时长不为零。"""
    cfg = IntervalTriggerConfig(**kwargs)
    assert cfg.type == "interval"


# ---------------------------------------------------------------------------
# DOW set expansion — semantic fire dates (not endpoint-only mapping)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dow_expr", "expected_weekdays"),
    [
        # Unix 0-2 = Sun,Mon,Tue
        ("0-2", {"Sun", "Mon", "Tue"}),
        # Unix 5-7 = Fri,Sat,Sun (7→0)
        ("5-7", {"Fri", "Sat", "Sun"}),
        # Unix */2 = 0,2,4,6 = Sun,Tue,Thu,Sat
        ("*/2", {"Sun", "Tue", "Thu", "Sat"}),
    ],
)
def test_dow_set_expansion_semantic_fire_dates(
    dow_expr: str, expected_weekdays: set[str]
):
    cron = f"0 12 * * {dow_expr}"
    # 从周日开始收集两周触发日
    start = datetime(2026, 7, 19, 0, 0, tzinfo=UTC)  # Sunday
    fires = _cron_fire_weekdays(cron, start=start, count=14)
    assert set(fires) == expected_weekdays
    # 构建触发器本身不应因 6-1 之类非法 range 失败
    trigger = build_trigger(CronTriggerConfig(cron=cron), timezone=UTC)
    field_map = {f.name: str(f) for f in trigger.fields}
    # 展开后应为逗号列表而非跨周非法 range
    assert (
        "-" not in field_map["day_of_week"] or field_map["day_of_week"].count("-") == 0
    )


def test_dow_0_2_not_endpoint_mapped_to_illegal_range():
    """旧 endpoint 映射会把 0-2 变成 APS 6-1 并 ValueError。"""
    trigger = build_trigger(CronTriggerConfig(cron="0 12 * * 0-2"), timezone=UTC)
    field_map = {f.name: str(f) for f in trigger.fields}
    # APS: Sun=6, Mon=0, Tue=1 → "0,1,6"
    assert set(field_map["day_of_week"].split(",")) == {"0", "1", "6"}


def test_dow_mixed_named_numeric_mon_and_zero():
    """Unix mon,0 = Monday + Sunday；名称保留、数字映射为 APS 6。"""
    cron = "0 12 * * mon,0"
    start = datetime(2026, 7, 19, 0, 0, tzinfo=UTC)  # Sunday
    fires = _cron_fire_weekdays(cron, start=start, count=14)
    assert set(fires) == {"Mon", "Sun"}

    trigger = build_trigger(CronTriggerConfig(cron=cron), timezone=UTC)
    field_map = {f.name: str(f) for f in trigger.fields}
    # mon 原样；Unix 0 → APS 6
    parts = field_map["day_of_week"].split(",")
    assert "mon" in parts
    assert "6" in parts
    # 旧逻辑整串透传 mon,0 在 APS 下只等于 Monday
    assert set(fires) != {"Mon"}


def test_dow_mixed_named_numeric_mon_and_range():
    """Unix mon,0-2 = Monday + Sun/Mon/Tue → 语义为 Sun,Mon,Tue。"""
    cron = "0 12 * * mon,0-2"
    start = datetime(2026, 7, 19, 0, 0, tzinfo=UTC)
    fires = _cron_fire_weekdays(cron, start=start, count=14)
    assert set(fires) == {"Sun", "Mon", "Tue"}

    trigger = build_trigger(CronTriggerConfig(cron=cron), timezone=UTC)
    field_map = {f.name: str(f) for f in trigger.fields}
    parts = field_map["day_of_week"].split(",")
    assert "mon" in parts
    # Unix 0-2 → APS 0,1,6
    assert {"0", "1", "6"}.issubset(set(parts))


def test_dow_bare_numeric_with_step_expands_to_max():
    """回归 ``5/2`` 静默丢弃步长的缺陷。

    修复前 ``5/2`` 展开为 ``{5}``（仅周五），周日丢失且无报错；
    修复后 ``5/2`` 等价 ``5-7/2`` → Unix {5,7} = 周五、周日（7→0）。
    """
    cron = "0 12 * * 5/2"
    start = datetime(2026, 7, 19, 0, 0, tzinfo=UTC)  # Sunday
    fires = _cron_fire_weekdays(cron, start=start, count=14)
    assert set(fires) == {"Fri", "Sun"}

    trigger = build_trigger(CronTriggerConfig(cron=cron), timezone=UTC)
    field_map = {f.name: str(f) for f in trigger.fields}
    # Unix 5 (Fri) → APS 4；Unix 7 (Sun, 由 7→0 规一) → APS 6
    # 旧逻辑此处仅产生 "4"（周五），周日被吞。
    assert set(field_map["day_of_week"].split(",")) == {"4", "6"}


def test_dow_bare_numeric_step_from_zero():
    """``0/3`` 等价 ``0-7/3`` → Unix {0,3,6} = Sun,Wed,Sat。"""
    cron = "0 12 * * 0/3"
    start = datetime(2026, 7, 19, 0, 0, tzinfo=UTC)  # Sunday
    fires = _cron_fire_weekdays(cron, start=start, count=14)
    assert set(fires) == {"Sun", "Wed", "Sat"}


def test_dow_bare_numeric_without_step_still_single():
    """无 ``/`` 的单值不得被错误展开到字段上界。"""
    cron = "0 12 * * 5"
    trigger = build_trigger(CronTriggerConfig(cron=cron), timezone=UTC)
    field_map = {f.name: str(f) for f in trigger.fields}
    # Unix 5 (Fri) → APS 4，且仅此一个值
    assert set(field_map["day_of_week"].split(",")) == {"4"}


def test_decode_dow_bare_numeric_step_uses_aps_hi():
    """解码方向 ``hi`` 必须为 6（APS 星期上界无 7）。

    APS ``1/3`` 语义为 {1,4} = Tue,Fri，反映射 ``aps_dow_to_unix`` 得
    Unix {2,5}。若误用 ``hi=7``，``1/3`` 会展开为 {1,4,7}，7 被规一为 0
    再经 ``aps_dow_to_unix(0)=1`` 伪造出额外的周一。
    """
    trigger = CronTrigger(day_of_week="1/3", minute="0", hour="12", day="*", month="*")
    _ttype, decoded = decode_trigger(trigger)
    # APS 1 (Tue) → Unix 2；APS 4 (Fri) → Unix 5；不得出现额外周一 1。
    assert decoded.cron.split()[-1] == "2,5"
    assert "1" not in decoded.cron.split()[-1].split(",")


def test_encode_decode_round_trip_bare_step_dow():
    """``0 12 * * 5/2`` 构建→解码后语义仍为 Fri + Sun。

    绕过字节一致（解码侧重排为逗号升序列表），仅校验语义触发星期。
    """
    original_cron = "0 12 * * 5/2"
    trigger = build_trigger(CronTriggerConfig(cron=original_cron), timezone=UTC)
    _ttype, decoded = decode_trigger(trigger)

    start = datetime(2026, 7, 19, 0, 0, tzinfo=UTC)  # Sunday
    fires = _cron_fire_weekdays(decoded.cron, start=start, count=14)
    assert set(fires) == {"Fri", "Sun"}


# ---------------------------------------------------------------------------
# encode_execution_kwargs + kwargs decoder
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
    assert kwargs["trigger_config"]["type"] == "cron"
    assert kwargs["trigger_config"]["cron"] == "0 9 * * *"

    # decode path only reads pre_tasks
    assert decode_pre_tasks_from_job_kwargs(kwargs) == kwargs["pre_tasks"]
    assert decode_pre_tasks_from_job_kwargs({"preTasks": CANONICAL_PRE}) == []
    assert decode_pre_tasks_from_job_kwargs({}) == []


@pytest.mark.parametrize(
    "trigger_config",
    [
        DateTriggerConfig(run_date=datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)),
        IntervalTriggerConfig(hours=1),
    ],
)
def test_encode_execution_kwargs_wakeup_non_cron_raises(trigger_config):
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
            trigger_config=trigger_config,
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
    assert kwargs["trigger_config"]["cron"] == "0 9 * * *"


def test_decode_scheduled_task_from_kwargs_complete():
    run_date = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)
    kwargs = encode_execution_kwargs(
        task_id="job-date",
        task_name="once",
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
        wakeup_enabled=False,
        trigger_config=DateTriggerConfig(run_date=run_date),
    )
    task = decode_scheduled_task_from_kwargs(kwargs)
    assert task.id == "job-date"
    assert task.name == "once"
    assert isinstance(task.trigger_config, DateTriggerConfig)
    assert task.trigger_config.run_date == run_date
    assert task.device is not None
    assert task.device.device_address == "127.0.0.1:5555"
    assert len(task.preTasks) == 1
    assert task.wakeup_enabled is False


def test_decode_scheduled_task_from_kwargs_missing_trigger_raises():
    with pytest.raises(SchedulerJobDecodeError, match="trigger_config"):
        decode_scheduled_task_from_kwargs(
            {
                "task_id": "x",
                "task_name": "n",
                "task_list": ["Main"],
                "task_options": {},
                "pre_tasks": [],
                "wakeup_enabled": False,
            }
        )


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
    assert (
        not hasattr(task, "trigger_type") or "trigger_type" not in task.model_fields_set
    )
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
# Differential + byte-identity guards for the _JobKwargs unification
# ---------------------------------------------------------------------------


def test_encode_execution_kwargs_byte_identical_snapshot():
    """Lock the exact wire output of encode_execution_kwargs.

    Captured before the _JobKwargs refactor; the dumped structure must remain
    byte-identical (deep-equal) afterwards. Uses DateTriggerConfig to also
    guard must-hold #1: mode="python" must keep datetime objects as datetimes
    in the pickled APS kwargs (not json-serialize them to strings).
    """
    device = ScheduledTaskDeviceConfig(
        controller_name="ADB",
        device_type="Adb",
        device_address="127.0.0.1:5555",
    )
    pt = PreTaskCommand(id="pt-1", command="echo hi", enabled=True, timeout=30)
    run_date = datetime(2026, 7, 19, 9, 0, tzinfo=UTC)
    trigger_config = DateTriggerConfig(run_date=run_date)

    actual = encode_execution_kwargs(
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
        trigger_config=trigger_config,
    )

    expected = {
        "task_id": "tid-1",
        "task_name": "name",
        "task_description": "desc",
        "task_list": ["Main"],
        "task_options": {"Main": {"opt": "v"}},
        "pre_tasks": [pt.model_dump()],
        "controller_name": "ADB",
        "device": device.model_dump(),
        "resource_name": "Official",
        "wakeup_enabled": False,
        "trigger_config": trigger_config.model_dump(mode="python"),
    }

    assert actual == expected
    # must-hold #1: datetime stays a datetime, not a string.
    assert isinstance(actual["trigger_config"]["run_date"], datetime)
    assert actual["trigger_config"]["run_date"] == run_date


def test_decode_lenient_and_strict_agree_for_same_kwargs():
    """Differential: for the same kwargs, the lenient and strict decoders must
    agree on id, name, description, wakeup_enabled, and trigger_config.

    This is the entire point of the Part 2 unification. Before the merge, the
    strict decoder raised a raw pydantic ValidationError on an empty task_name
    (ScheduledTask.name has min_length=1) while the lenient decoder fell back to
    task_id — the same "invisible in the UI yet still fires" zombie class fixed
    from the other direction in scheduler_manager. After unification both adopt
    the lenient `name if name else task_id` fallback.

    The strict decoder reads its trigger from the live APS trigger
    (decode_trigger(job.trigger)); the lenient one reads kwargs["trigger_config"].
    For this test the two sources describe the same trigger, so the decoded
    trigger_config objects must be equal.
    """
    trigger_config = CronTriggerConfig(cron="0 9 * * *")
    trigger = build_trigger(trigger_config)
    next_run_time = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)
    kwargs = encode_execution_kwargs(
        task_id="diff-1",
        task_name="",  # empty name is what triggers the strict/lenient split
        task_description="desc",
        task_list=["Main"],
        task_options={},
        pre_tasks=[],
        controller_name=None,
        device=None,
        resource_name=None,
        wakeup_enabled=False,
        trigger_config=trigger_config,
    )
    job = SimpleNamespace(
        id="diff-1",
        kwargs=kwargs,
        trigger=trigger,
        next_run_time=next_run_time,
    )

    lenient = decode_scheduled_task_from_kwargs(
        kwargs, enabled=True, next_run_time=next_run_time
    )
    strict = decode_job_to_scheduled_task(job, normalize=_identity_normalize)

    assert strict.id == lenient.id == "diff-1"
    # both must fall back to task_id rather than strict raising ValidationError
    assert strict.name == lenient.name == "diff-1"
    assert strict.description == lenient.description == "desc"
    assert strict.wakeup_enabled is lenient.wakeup_enabled is False
    assert strict.trigger_config == lenient.trigger_config


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
