"""Pure APS job encode/decode helpers for SchedulerManager.

Owns trigger construction/reconstruction and execution kwargs schema.
Does not import SchedulerManager or runtime/worker state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    ScheduledTask,
    ScheduledTaskDeviceConfig,
    TaskOptionsByTask,
    TriggerConfig,
)
from services.native_cron import aps_dow_to_unix, unix_dow_to_aps

TriggerType = Literal["cron", "date", "interval"]
NormalizePayload = Callable[
    [Any, Any, Any],
    tuple[list[str], TaskOptionsByTask, list[Any]],
]

_MISFIRE_GRACE = timedelta(minutes=15)


class SchedulerJobDecodeError(Exception):
    """Persisted APS job cannot be decoded into a ScheduledTask."""

    def __init__(
        self,
        message: str,
        *,
        job_id: str | None = None,
        cause: BaseException | None = None,
    ):
        self.job_id = job_id
        self.cause = cause
        prefix = f"job {job_id}: " if job_id else ""
        super().__init__(f"{prefix}{message}")


def decode_wakeup_enabled(raw: Any, *, job_id: str | None = None) -> bool:
    """Decode APS wakeup_enabled: missing/None → False; bool only otherwise."""
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    raise SchedulerJobDecodeError(
        f"invalid wakeup_enabled: {raw!r}",
        job_id=job_id,
    )


def _map_dow_expr(expr: str, mapper: Callable[[int], int]) -> str:
    """Map numeric day-of-week tokens in a cron field expression.

    Preserves ``*``, steps (``/N``), lists, and ranges. Name tokens pass through.
    """
    if expr == "*":
        return "*"
    if "/" in expr:
        base, step = expr.split("/", 1)
        return f"{_map_dow_expr(base, mapper)}/{step}"
    if "," in expr:
        return ",".join(_map_dow_expr(part, mapper) for part in expr.split(","))
    if "-" in expr:
        left, right = expr.split("-", 1)
        if left.isdigit() and right.isdigit():
            return f"{mapper(int(left))}-{mapper(int(right))}"
        return expr
    if expr.isdigit():
        return str(mapper(int(expr)))
    return expr


def build_trigger(
    trigger_config: TriggerConfig,
    *,
    timezone: Any = None,
) -> CronTrigger | DateTrigger | IntervalTrigger:
    """Build an APScheduler trigger from TriggerConfig.

    Cron day-of-week uses Unix semantics (0/7=Sunday); mapped to APS (0=Monday).
    """
    if isinstance(trigger_config, CronTriggerConfig):
        parts = trigger_config.cron.split()
        if len(parts) != 5:
            raise ValueError(f"无效的 Cron 表达式: {trigger_config.cron}")
        minute, hour, day, month, day_of_week = parts
        kwargs: dict[str, Any] = {
            "minute": minute,
            "hour": hour,
            "day": day,
            "month": month,
            "day_of_week": _map_dow_expr(day_of_week, unix_dow_to_aps),
        }
        if timezone is not None:
            kwargs["timezone"] = timezone
        return CronTrigger(**kwargs)
    if isinstance(trigger_config, DateTriggerConfig):
        return DateTrigger(run_date=trigger_config.run_date)
    if isinstance(trigger_config, IntervalTriggerConfig):
        return IntervalTrigger(
            weeks=trigger_config.weeks or 0,
            days=trigger_config.days or 0,
            hours=trigger_config.hours or 0,
            minutes=trigger_config.minutes or 0,
            seconds=trigger_config.seconds or 0,
            start_date=trigger_config.start_date,
            end_date=trigger_config.end_date,
        )
    raise ValueError(f"未知的触发器类型: {type(trigger_config)}")


def decode_trigger(trigger: Any) -> tuple[TriggerType, TriggerConfig]:
    """Rebuild (trigger_type, TriggerConfig) from an APScheduler trigger.

    Raises ValueError for unknown/corrupt triggers. Never invents a default cron.
    Cron day-of-week is reverse-mapped from APS (0=Monday) to Unix (0=Sunday).
    """
    if isinstance(trigger, CronTrigger):
        required_fields = ("minute", "hour", "day", "month", "day_of_week")
        field_map = {field.name: str(field) for field in trigger.fields}
        missing = [name for name in required_fields if name not in field_map]
        if missing:
            raise ValueError(
                f"CronTrigger missing required field(s): {', '.join(missing)}"
            )
        dow_unix = _map_dow_expr(field_map["day_of_week"], aps_dow_to_unix)
        cron = " ".join(
            [
                field_map["minute"],
                field_map["hour"],
                field_map["day"],
                field_map["month"],
                dow_unix,
            ]
        )
        return "cron", CronTriggerConfig(cron=cron)

    if isinstance(trigger, DateTrigger):
        run_date = getattr(trigger, "run_date", None)
        if run_date is None:
            raise ValueError("DateTrigger 缺少 run_date")
        return "date", DateTriggerConfig(run_date=run_date)

    if isinstance(trigger, IntervalTrigger):
        interval = getattr(trigger, "interval", None)
        total_seconds = int(interval.total_seconds()) if interval is not None else 0

        week_seconds = 7 * 24 * 60 * 60
        day_seconds = 24 * 60 * 60

        weeks, remainder = divmod(total_seconds, week_seconds)
        days, remainder = divmod(remainder, day_seconds)
        hours, remainder = divmod(remainder, 60 * 60)
        minutes, seconds = divmod(remainder, 60)

        return "interval", IntervalTriggerConfig(
            weeks=weeks or None,
            days=days or None,
            hours=hours or None,
            minutes=minutes or None,
            seconds=seconds or None,
            start_date=getattr(trigger, "start_date", None),
            end_date=getattr(trigger, "end_date", None),
        )

    raise ValueError(f"未知的触发器类型: {type(trigger)}")


def decode_pre_tasks_from_job_kwargs(kwargs: Mapping[str, Any]) -> Any:
    """Decode persisted pre-tasks from job kwargs.

    Reads only the ``pre_tasks`` key. Missing key returns ``[]``.
    No legacy ``preTasks`` fallback.
    """
    if "pre_tasks" in kwargs:
        return kwargs["pre_tasks"]
    return []


def _dump_pre_tasks(pre_tasks: Sequence[Any]) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = []
    for item in pre_tasks:
        if isinstance(item, BaseModel):
            dumped.append(item.model_dump())
        elif isinstance(item, Mapping):
            dumped.append(dict(item))
        else:
            raise TypeError(f"unsupported pre-task item type: {type(item)}")
    return dumped


def _dump_device(device: Any) -> dict[str, Any] | None:
    if device is None:
        return None
    if isinstance(device, BaseModel):
        return device.model_dump()
    if isinstance(device, Mapping):
        return dict(device)
    raise TypeError(f"unsupported device type: {type(device)}")


def encode_execution_kwargs(
    *,
    task_id: str,
    task_name: str,
    task_description: str | None,
    task_list: list[str],
    task_options: TaskOptionsByTask,
    pre_tasks: Sequence[Any],
    controller_name: str | None,
    device: Any,
    resource_name: str | None,
    wakeup_enabled: bool = False,
    trigger_config: TriggerConfig | None = None,
) -> dict[str, Any]:
    """Encode complete APS job kwargs for add_job / modify_job.

    Writes ``pre_tasks`` and always includes ``wakeup_enabled`` bool.
    ``wakeup_enabled=True`` requires a ``CronTriggerConfig`` trigger.
    """
    if not isinstance(wakeup_enabled, bool):
        raise ValueError(f"invalid wakeup_enabled: {wakeup_enabled!r}")
    if wakeup_enabled and not isinstance(trigger_config, CronTriggerConfig):
        raise ValueError("wakeup_enabled 仅支持 cron 触发器")
    return {
        "task_id": task_id,
        "task_name": task_name,
        "task_description": task_description or "",
        "task_list": task_list,
        "task_options": task_options,
        "pre_tasks": _dump_pre_tasks(pre_tasks),
        "controller_name": controller_name,
        "device": _dump_device(device),
        "resource_name": resource_name,
        "wakeup_enabled": wakeup_enabled,
    }


def _last_fire_leq(
    trigger: CronTrigger,
    start: datetime,
    now: datetime,
) -> datetime | None:
    """Iterate get_next_fire_time from start to the last fire time <= now."""
    last: datetime | None = None
    current = trigger.get_next_fire_time(None, start)
    while current is not None and current <= now:
        last = current
        current = trigger.get_next_fire_time(last, last)
    return last


def compute_occurrence(trigger: TriggerConfig, now: datetime) -> datetime:
    """Compute the occurrence timestamp for a scheduled fire at ``now``.

    - cron: last fire time <= now via CronTrigger.get_next_fire_time
      (primary window now-15min; extended lookback if empty)
    - date: run_date
    - interval: now truncated to the minute

    ``now`` should be timezone-aware (local). Return value stays aware.
    """
    if isinstance(trigger, DateTriggerConfig):
        return trigger.run_date

    if isinstance(trigger, IntervalTriggerConfig):
        return now.replace(second=0, microsecond=0)

    if isinstance(trigger, CronTriggerConfig):
        tz = now.tzinfo
        if tz is None:
            # Fall back to local zone name if a naive datetime slips through
            tz = ZoneInfo("UTC")
        built = build_trigger(trigger, timezone=tz)
        assert isinstance(built, CronTrigger)
        last = _last_fire_leq(built, now - _MISFIRE_GRACE, now)
        if last is not None:
            return last
        # Extended lookback (e.g. 8:55 for daily 09:00 → previous day 09:00).
        # Caller normally only invokes this inside grace; tests cover pre-fire.
        last = _last_fire_leq(built, now - timedelta(days=8), now)
        if last is not None:
            return last
        return now.replace(second=0, microsecond=0)

    raise ValueError(f"未知的触发器类型: {type(trigger)}")


def decode_job_to_scheduled_task(
    job: Any,
    *,
    normalize: NormalizePayload,
) -> ScheduledTask:
    """Decode an APS Job into ScheduledTask.

    ``normalize`` receives (task_list, task_options, raw_pre_tasks) and returns
    normalized execution payload. Raises SchedulerJobDecodeError on trigger
    corruption; never invents a default cron and never mutates the job.
    """
    job_id = getattr(job, "id", None)
    kwargs = getattr(job, "kwargs", None) or {}
    if not isinstance(kwargs, Mapping):
        raise SchedulerJobDecodeError("job kwargs is not a mapping", job_id=job_id)

    try:
        _trigger_type, trigger_config = decode_trigger(getattr(job, "trigger", None))
    except Exception as exc:
        raise SchedulerJobDecodeError(
            f"trigger decode failed: {exc}",
            job_id=job_id,
            cause=exc,
        ) from exc

    task_list, task_options, pre_tasks = normalize(
        kwargs.get("task_list", []),
        kwargs.get("task_options", {}),
        decode_pre_tasks_from_job_kwargs(kwargs),
    )

    device_raw = kwargs.get("device", None)
    try:
        device = ScheduledTaskDeviceConfig(**device_raw) if device_raw else None
    except Exception as exc:
        raise SchedulerJobDecodeError(
            f"device decode failed: {exc}",
            job_id=job_id,
            cause=exc,
        ) from exc

    description = kwargs.get("task_description", "")
    wakeup_enabled = decode_wakeup_enabled(
        kwargs.get("wakeup_enabled", None),
        job_id=str(job_id) if job_id is not None else None,
    )

    return ScheduledTask(
        id=str(job_id) if job_id is not None else "",
        name=kwargs.get("task_name", "") or "",
        description=description,
        enabled=getattr(job, "next_run_time", None) is not None,
        trigger_config=trigger_config,
        task_list=task_list,
        task_options=task_options,
        preTasks=pre_tasks,
        next_run_time=getattr(job, "next_run_time", None),
        controller_name=kwargs.get("controller_name", None),
        device=device,
        resource_name=kwargs.get("resource_name", None),
        wakeup_enabled=wakeup_enabled,
    )
