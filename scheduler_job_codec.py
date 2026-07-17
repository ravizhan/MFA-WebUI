"""Pure APS job encode/decode helpers for SchedulerManager.

Owns trigger construction/reconstruction and execution kwargs schema.
Does not import SchedulerManager or runtime/worker state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Optional

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

TriggerType = Literal["cron", "date", "interval"]
# Stored field remains system_scope for APS/job compatibility.
# Runtime value is always "user" when wakeup is enabled (legacy "system" → "user").
SystemScopeValue = Literal["user"]
_LEGACY_WAKEUP_SCOPES = frozenset({"user", "system"})
NormalizePayload = Callable[
    [Any, Any, Any],
    tuple[list[str], TaskOptionsByTask, list[Any]],
]


class SchedulerJobDecodeError(Exception):
    """Persisted APS job cannot be decoded into a ScheduledTask."""

    def __init__(
        self,
        message: str,
        *,
        job_id: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ):
        self.job_id = job_id
        self.cause = cause
        prefix = f"job {job_id}: " if job_id else ""
        super().__init__(f"{prefix}{message}")


def normalize_wakeup_scope(
    raw: Any, *, job_id: Optional[str] = None
) -> Optional[SystemScopeValue]:
    """Normalize wakeup flag: None | 'user' | legacy 'system' → None | 'user'.

    Both historical 'user' and 'system' mean user-level native wakeup enabled.
    """
    if raw is None:
        return None
    if isinstance(raw, str) and raw in _LEGACY_WAKEUP_SCOPES:
        return "user"
    raise SchedulerJobDecodeError(
        f"invalid system_scope: {raw!r}",
        job_id=job_id,
    )


def decode_system_scope(
    raw: Any, *, job_id: Optional[str] = None
) -> Optional[SystemScopeValue]:
    """Decode persisted system_scope; legacy 'system' becomes user wakeup."""
    return normalize_wakeup_scope(raw, job_id=job_id)


def build_trigger(trigger_config: TriggerConfig) -> CronTrigger | DateTrigger | IntervalTrigger:
    """Build an APScheduler trigger from TriggerConfig."""
    if isinstance(trigger_config, CronTriggerConfig):
        parts = trigger_config.cron.split()
        if len(parts) != 5:
            raise ValueError(f"无效的 Cron 表达式: {trigger_config.cron}")
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
        )
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
    """
    if isinstance(trigger, CronTrigger):
        required_fields = ("minute", "hour", "day", "month", "day_of_week")
        field_map = {field.name: str(field) for field in trigger.fields}
        missing = [name for name in required_fields if name not in field_map]
        if missing:
            raise ValueError(
                f"CronTrigger missing required field(s): {', '.join(missing)}"
            )
        cron = " ".join(field_map[name] for name in required_fields)
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

    Canonical key is ``pre_tasks``. Legacy jobs may still store ``preTasks``.
    Prefer canonical when the key is present — including an explicit empty list —
    and only fall back to legacy when the canonical key is absent.
    """
    if "pre_tasks" in kwargs:
        return kwargs["pre_tasks"]
    if "preTasks" in kwargs:
        return kwargs["preTasks"]
    return []


def resolve_execute_pre_tasks(
    pre_tasks: Optional[list[dict]],
    preTasks: Optional[list[dict]],
) -> list[dict]:
    """Resolve pre-tasks for the persisted callable entrypoint.

    Prefer canonical ``pre_tasks`` when provided (including ``[]``). Fall back to
    legacy ``preTasks`` only when the canonical argument is omitted (``None``).
    """
    if pre_tasks is not None:
        return pre_tasks
    if preTasks is not None:
        return preTasks
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


def _dump_device(device: Any) -> Optional[dict[str, Any]]:
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
    task_description: Optional[str],
    task_list: list[str],
    task_options: TaskOptionsByTask,
    pre_tasks: Sequence[Any],
    controller_name: Optional[str],
    device: Any,
    resource_name: Optional[str],
    system_scope: Optional[Literal["user", "system"]] = None,
) -> dict[str, Any]:
    """Encode complete APS job kwargs for add_job / modify_job.

    Writes canonical ``pre_tasks`` and always includes ``system_scope`` (may be
    None). Legacy ``system`` is normalized to ``user`` before persist.
    Callers must pass the full kwargs dict to modify_job so the store fully
    replaces the previous kwargs payload.
    """
    normalized_scope: Optional[SystemScopeValue] = None
    if system_scope is not None:
        if system_scope not in _LEGACY_WAKEUP_SCOPES:
            raise ValueError(f"invalid system_scope: {system_scope!r}")
        normalized_scope = "user"
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
        "system_scope": normalized_scope,
    }


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
        trigger_type, trigger_config = decode_trigger(getattr(job, "trigger", None))
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

    # Preserve persisted description exactly (empty string stays empty string).
    description = kwargs.get("task_description", "")
    # Missing key → None (legacy jobs); present invalid → decode error.
    system_scope = decode_system_scope(
        kwargs.get("system_scope", None),
        job_id=str(job_id) if job_id is not None else None,
    )

    return ScheduledTask(
        id=str(job_id) if job_id is not None else "",
        name=kwargs.get("task_name", "") or "",
        description=description,
        enabled=getattr(job, "next_run_time", None) is not None,
        trigger_type=trigger_type,
        trigger_config=trigger_config,
        task_list=task_list,
        task_options=task_options,
        preTasks=pre_tasks,
        next_run_time=getattr(job, "next_run_time", None),
        controller_name=kwargs.get("controller_name", None),
        device=device,
        resource_name=kwargs.get("resource_name", None),
        system_scope=system_scope,
    )
