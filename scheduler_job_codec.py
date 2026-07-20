"""APS 调度任务编解码：触发器构建/还原与执行 kwargs 序列化。

不依赖 SchedulerManager 或运行时状态，便于独立测试与复用。
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
    """持久化 APS job 无法解码为 ScheduledTask。"""

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
    """解码 wakeup_enabled：缺失/None 视为 False，其余仅接受 bool。"""
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    raise SchedulerJobDecodeError(
        f"invalid wakeup_enabled: {raw!r}",
        job_id=job_id,
    )


def _map_dow_expr(expr: str, mapper: Callable[[int], int]) -> str:
    """映射 cron 星期字段中的数字 token（保留 *、步长、列表、范围；名称原样通过）。"""
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
    """由 TriggerConfig 构建 APScheduler 触发器。

    Cron 星期采用 Unix 语义（0/7=周日），写入 APS 前映射为 0=周一。
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
    """从 APS 触发器还原 (类型, TriggerConfig)。

    未知/损坏触发器抛 ValueError，不臆造默认 cron。
    星期字段从 APS（0=周一）反映射为 Unix（0=周日）。
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
    """从 job kwargs 读取 pre_tasks；缺省返回 []，无旧键 preTasks 回退。"""
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
    """编码 add_job/modify_job 用的完整 APS kwargs。

    始终写入 bool 型 wakeup_enabled；为 True 时触发器必须是 CronTriggerConfig。
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
    """自 start 起迭代 get_next_fire_time，取最后一个 ≤ now 的触发时刻。"""
    last: datetime | None = None
    current = trigger.get_next_fire_time(None, start)
    while current is not None and current <= now:
        last = current
        current = trigger.get_next_fire_time(last, last)
    return last


def compute_occurrence(trigger: TriggerConfig, now: datetime) -> datetime:
    """计算「在 now 时刻应归属」的计划触发时间戳（保持时区感知）。

    cron：优先 15 分钟 misfire 窗口内最近触发；落空再扩展回看。
    date：run_date；interval：截断到分钟。
    """
    if isinstance(trigger, DateTriggerConfig):
        return trigger.run_date

    if isinstance(trigger, IntervalTriggerConfig):
        return now.replace(second=0, microsecond=0)

    if isinstance(trigger, CronTriggerConfig):
        tz = now.tzinfo
        if tz is None:
            # 无时区时退回 UTC，避免 naive 比较异常
            tz = ZoneInfo("UTC")
        built = build_trigger(trigger, timezone=tz)
        assert isinstance(built, CronTrigger)
        last = _last_fire_leq(built, now - _MISFIRE_GRACE, now)
        if last is not None:
            return last
        # 扩展回看：如 8:55 对每日 09:00 应落到前一日 09:00
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
    """将 APS Job 解码为 ScheduledTask。

    normalize 负责规范化 (task_list, task_options, pre_tasks)；
    触发器损坏抛 SchedulerJobDecodeError，不改写 job、不臆造默认 cron。
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
