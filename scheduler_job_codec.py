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
    PreTaskCommand,
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


def _expand_numeric_cron_field(expr: str, *, lo: int, hi: int) -> set[int] | None:
    """将仅含数字/* / range/list/step 的 cron 字段展开为集合。

    含名称 token 时返回 None（由调用方原样透传）。
    """
    if expr == "*":
        return set(range(lo, hi + 1))

    result: set[int] = set()
    for part in expr.split(","):
        if not part:
            raise ValueError(f"无效的 cron 字段片段: {expr!r}")

        step = 1
        base = part
        if "/" in part:
            base, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                raise ValueError(f"无效的 cron 步长: {part!r}")
            step = int(step_s)
            if base == "":
                base = "*"

        if base == "*":
            result.update(range(lo, hi + 1, step))
            continue

        if "-" in base:
            left, right = base.split("-", 1)
            if not (left.isdigit() and right.isdigit()):
                return None
            start_v, end_v = int(left), int(right)
            if start_v > end_v:
                raise ValueError(f"cron 范围起点不能大于终点: {part!r}")
            result.update(range(start_v, end_v + 1, step))
            continue

        if base.isdigit():
            # 单值带 step 时 cron 语义仍只取该点
            result.add(int(base))
            continue

        # mon / tue 等名称：不在此展开
        return None

    return result


def _map_numeric_dow_segment(segment: str, mapper: Callable[[int], int]) -> str:
    """展开并映射单个纯数字星期片段（含 range/step/*）；非数字返回原串。"""
    expanded = _expand_numeric_cron_field(segment, lo=0, hi=7)
    if expanded is None:
        return segment

    mapped: set[int] = set()
    for raw in expanded:
        if raw < 0 or raw > 7:
            raise ValueError(f"星期字段越界: {raw}")
        # Unix 7=周日 → 0；APS 无 7
        normalized = 0 if raw == 7 else raw
        mapped.add(mapper(normalized))

    if not mapped:
        raise ValueError(f"星期字段展开为空: {segment!r}")
    return ",".join(str(n) for n in sorted(mapped))


def _map_dow_expr(expr: str, mapper: Callable[[int], int]) -> str:
    """映射 cron 星期字段：逗号分段独立处理。

    - 数字片段（0、0-2、*/2、5-7 等）先展开再逐点映射后重编码
    - 名称片段（mon、mon-fri 等）原样保留
    - 混合如 mon,0 / mon,0-2 分别处理，语义为名称日 + 映射后的数字日
    """
    if expr == "*":
        return "*"

    # 按逗号分段：名称与数字互不吞没
    parts = expr.split(",")
    if not parts or any(p == "" for p in parts):
        raise ValueError(f"无效的星期字段: {expr!r}")

    return ",".join(_map_numeric_dow_segment(part, mapper) for part in parts)


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


def _dump_trigger_config(trigger_config: TriggerConfig) -> dict[str, Any]:
    """序列化 TriggerConfig，供 APS job kwargs 持久化。"""
    if isinstance(trigger_config, BaseModel):
        return trigger_config.model_dump(mode="python")
    raise TypeError(f"unsupported trigger_config type: {type(trigger_config)}")


def _load_trigger_config(
    raw: Any,
    *,
    job_id: str | None = None,
) -> TriggerConfig:
    """从 kwargs 还原 TriggerConfig；缺失/损坏直接失败，无旧载荷回退。"""
    if not isinstance(raw, Mapping):
        raise SchedulerJobDecodeError(
            f"missing or invalid trigger_config: {raw!r}",
            job_id=job_id,
        )
    ttype = raw.get("type")
    try:
        if ttype == "cron":
            return CronTriggerConfig.model_validate(raw)
        if ttype == "date":
            return DateTriggerConfig.model_validate(raw)
        if ttype == "interval":
            return IntervalTriggerConfig.model_validate(raw)
    except Exception as exc:
        raise SchedulerJobDecodeError(
            f"trigger_config decode failed: {exc}",
            job_id=job_id,
            cause=exc,
        ) from exc
    raise SchedulerJobDecodeError(
        f"unknown trigger_config type: {ttype!r}",
        job_id=job_id,
    )


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
    trigger_config: TriggerConfig,
) -> dict[str, Any]:
    """编码 add_job/modify_job 用的完整 APS kwargs。

    始终写入 bool 型 wakeup_enabled 与完整 trigger_config；
    wakeup 为 True 时触发器必须是 CronTriggerConfig。
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
        "trigger_config": _dump_trigger_config(trigger_config),
    }


def decode_scheduled_task_from_kwargs(
    kwargs: Mapping[str, Any],
    *,
    enabled: bool = True,
    next_run_time: datetime | None = None,
    job_id: str | None = None,
) -> ScheduledTask:
    """仅从 callback/job kwargs 重建完整 ScheduledTask。

    供 APS 回调使用：DateTrigger 到期后 job 可能已被移除，不能再 get_task。
    要求 kwargs 含完整 trigger_config，无旧格式回退。
    """
    if not isinstance(kwargs, Mapping):
        raise SchedulerJobDecodeError("job kwargs is not a mapping", job_id=job_id)

    task_id = kwargs.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        # 兼容仅有 job.id 的调用方
        if isinstance(job_id, str) and job_id:
            task_id = job_id
        else:
            raise SchedulerJobDecodeError("missing task_id", job_id=job_id)

    trigger_config = _load_trigger_config(
        kwargs.get("trigger_config"),
        job_id=task_id,
    )

    task_list_raw = kwargs.get("task_list", [])
    if not isinstance(task_list_raw, list):
        raise SchedulerJobDecodeError("invalid task_list", job_id=task_id)
    task_list = [tid for tid in task_list_raw if isinstance(tid, str)]

    task_options_raw = kwargs.get("task_options", {})
    if not isinstance(task_options_raw, Mapping):
        raise SchedulerJobDecodeError("invalid task_options", job_id=task_id)
    task_options: TaskOptionsByTask = dict(task_options_raw)  # type: ignore[arg-type]

    pre_raw = decode_pre_tasks_from_job_kwargs(kwargs)
    pre_tasks: list[PreTaskCommand] = []
    if isinstance(pre_raw, list):
        for item in pre_raw:
            if isinstance(item, PreTaskCommand):
                pre_tasks.append(item)
            elif isinstance(item, Mapping):
                try:
                    pre_tasks.append(PreTaskCommand.model_validate(item))
                except Exception as exc:
                    raise SchedulerJobDecodeError(
                        f"pre_tasks decode failed: {exc}",
                        job_id=task_id,
                        cause=exc,
                    ) from exc
            else:
                raise SchedulerJobDecodeError(
                    f"invalid pre_tasks item: {type(item)}",
                    job_id=task_id,
                )

    device_raw = kwargs.get("device", None)
    try:
        device = ScheduledTaskDeviceConfig(**device_raw) if device_raw else None
    except Exception as exc:
        raise SchedulerJobDecodeError(
            f"device decode failed: {exc}",
            job_id=task_id,
            cause=exc,
        ) from exc

    wakeup_enabled = decode_wakeup_enabled(
        kwargs.get("wakeup_enabled", None),
        job_id=task_id,
    )

    description = kwargs.get("task_description", "") or ""
    name = kwargs.get("task_name", "") or ""

    return ScheduledTask(
        id=task_id,
        name=name if name else task_id,
        description=description,
        enabled=enabled,
        trigger_config=trigger_config,
        task_list=task_list,
        task_options=task_options,
        preTasks=pre_tasks,
        next_run_time=next_run_time,
        controller_name=kwargs.get("controller_name", None),
        device=device,
        resource_name=kwargs.get("resource_name", None),
        wakeup_enabled=wakeup_enabled,
    )


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
