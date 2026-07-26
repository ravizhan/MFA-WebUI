"""APS 调度任务编解码：触发器构建/还原与执行 kwargs 序列化。

不依赖 SchedulerManager 或运行时状态，便于独立测试与复用。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator

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


def _expand_numeric_cron_field(expr: str, *, lo: int, hi: int) -> set[int] | None:
    """将仅含数字/* / range/list/step 的 cron 字段展开为集合。

    含名称 token 时返回 None（由调用方原样透传）。

    ``N/step`` 等价于 ``N-hi/step``（与 APS RangeExpression 语义一致），
    即从 N 起以 step 递增至字段上界 hi（含），并非仅取单点 N。
    """
    if expr == "*":
        return set(range(lo, hi + 1))

    result: set[int] = set()
    for part in expr.split(","):
        if not part:
            raise ValueError(f"无效的 cron 字段片段: {expr!r}")

        step = 1
        base = part
        has_step = "/" in part
        if has_step:
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
            start_v = int(base)
            if has_step:
                # N/step 等价 N-hi/step（与 APS RangeExpression 语义一致）
                result.update(range(start_v, hi + 1, step))
            else:
                result.add(start_v)
            continue

        # mon / tue 等名称：不在此展开
        return None

    return result


def _map_numeric_dow_segment(
    segment: str, mapper: Callable[[int], int], *, hi: int
) -> str:
    """展开并映射单个纯数字星期片段（含 range/step/*）；非数字返回原串。"""
    expanded = _expand_numeric_cron_field(segment, lo=0, hi=hi)
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


def _map_dow_expr(expr: str, mapper: Callable[[int], int], *, hi: int) -> str:
    """映射 cron 星期字段：逗号分段独立处理。

    - 数字片段（0、0-2、*/2、5-7、5/2 等）先展开再逐点映射后重编码
    - 名称片段（mon、mon-fri 等）原样保留
    - 混合如 mon,0 / mon,0-2 分别处理，语义为名称日 + 映射后的数字日

    ``hi`` 为星期字段上界，方向相关：
    编码侧（Unix 星期，0/7 均为周日）传 7；解码侧（APS 星期，0=周一..6=周日）
    传 6。两者不可混用：解码侧若传 7，``1/3`` 会将不存在的 APS 7 当作周日，
    归一为 0 后被 ``aps_dow_to_unix`` 映射出虚构的周一。
    """
    if expr == "*":
        return "*"

    # 按逗号分段：名称与数字互不吞没
    parts = expr.split(",")
    if not parts or any(p == "" for p in parts):
        raise ValueError(f"无效的星期字段: {expr!r}")

    return ",".join(_map_numeric_dow_segment(part, mapper, hi=hi) for part in parts)


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
            "day_of_week": _map_dow_expr(day_of_week, unix_dow_to_aps, hi=7),
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
        dow_unix = _map_dow_expr(field_map["day_of_week"], aps_dow_to_unix, hi=6)
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


# APS job kwargs 的线模型：encode 写入的 11 个字段。
# 编码经此模型路由（model_dump mode="python"），解码也由此统一校验/还原，
# 使 decode_scheduled_task_from_kwargs 与 decode_job_to_scheduled_task 收敛到同一来源。
class _JobKwargs(BaseModel):
    task_id: str | None = None
    task_name: str = ""
    task_description: str = ""
    task_list: list[str] = []
    task_options: dict[str, dict[str, Any]] = {}
    pre_tasks: list[dict[str, Any]] = []
    controller_name: str | None = None
    device: ScheduledTaskDeviceConfig | None = None
    resource_name: str | None = None
    wakeup_enabled: bool = False
    trigger_config: dict[str, Any] | None = None

    @field_validator("device", mode="before")
    @classmethod
    def _falsy_device_to_none(cls, v: Any) -> Any:
        # must-hold #3：{} / None / 缺失 -> None
        return None if not v else v

    @field_validator("task_description", mode="before")
    @classmethod
    def _none_desc_to_empty(cls, v: Any) -> Any:
        # must-hold #2：task_description 永不 None
        return v or ""

    @field_validator("wakeup_enabled", mode="before")
    @classmethod
    def _none_wakeup_to_false(cls, v: Any) -> Any:
        # 缺失/None -> False（取代原 decode_wakeup_enabled 的 isinstance 严格拒绝）
        return False if v is None else v

    @field_validator("pre_tasks", mode="before")
    @classmethod
    def _dump_pre_task_items(cls, v: Any) -> Any:
        # 取代 _dump_pre_tasks：PreTaskCommand 模型逐项 dump（mode="python"）
        if isinstance(v, list):
            return [
                item.model_dump(mode="python") if isinstance(item, BaseModel) else item
                for item in v
            ]
        return v

    @field_validator("trigger_config", mode="before")
    @classmethod
    def _dump_trigger(cls, v: Any) -> Any:
        # 取代 _dump_trigger_config：TriggerConfig 模型 -> dict（mode="python"）；
        # 解码侧保持原始 dict，触发器类型由 to_scheduled_task 按入口路径解析
        return v.model_dump(mode="python") if isinstance(v, BaseModel) else v


# 取代 _load_trigger_config 的 if-ladder：基于 discriminator 的 TypeAdapter。
_TRIGGER_ADAPTER = TypeAdapter(Annotated[TriggerConfig, Field(discriminator="type")])


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
    return _JobKwargs(
        task_id=task_id,
        task_name=task_name,
        task_description=task_description,
        task_list=task_list,
        task_options=task_options,
        pre_tasks=pre_tasks,
        controller_name=controller_name,
        device=device,
        resource_name=resource_name,
        wakeup_enabled=wakeup_enabled,
        trigger_config=trigger_config,
    ).model_dump(mode="python")


def to_scheduled_task(
    jkw: _JobKwargs,
    *,
    task_id: str,
    trigger_config: TriggerConfig,
    enabled: bool,
    next_run_time: datetime | None,
    normalize: NormalizePayload | None = None,
) -> ScheduledTask:
    """由 _JobKwargs 构建 ScheduledTask（两个解码入口共享）。

    name 为空回退 task_id（统一 lenient 行为，杜绝 strict 侧 name="" 裸
    ValidationError → 不可见却仍触发的僵尸任务）。trigger_config 由调用方按入口
    来源解析后传入。normalize=None 走 lenient（就地构建 PreTaskCommand），
    提供时走 strict（交由 normalize 处理 task_list/task_options/pre_tasks）。
    """
    name = jkw.task_name if jkw.task_name else task_id
    if normalize is None:
        task_list = list(jkw.task_list)
        task_options: TaskOptionsByTask = dict(jkw.task_options)
        pre_tasks: list[PreTaskCommand] = []
        for item in jkw.pre_tasks:
            if isinstance(item, PreTaskCommand):
                pre_tasks.append(item)
                continue
            try:
                pre_tasks.append(PreTaskCommand.model_validate(item))
            except Exception as exc:
                raise SchedulerJobDecodeError(
                    f"pre_tasks decode failed: {exc}",
                    job_id=task_id,
                    cause=exc,
                ) from exc
    else:
        task_list, task_options, pre_tasks = normalize(
            jkw.task_list, jkw.task_options, jkw.pre_tasks
        )
    return ScheduledTask(
        id=task_id,
        name=name,
        description=jkw.task_description,
        enabled=enabled,
        trigger_config=trigger_config,
        task_list=task_list,
        task_options=task_options,
        preTasks=pre_tasks,
        next_run_time=next_run_time,
        controller_name=jkw.controller_name,
        device=jkw.device,
        resource_name=jkw.resource_name,
        wakeup_enabled=jkw.wakeup_enabled,
    )


def decode_scheduled_task_from_kwargs(
    kwargs: Mapping[str, Any],
    *,
    enabled: bool = True,
    next_run_time: datetime | None = None,
    job_id: str | None = None,
) -> ScheduledTask:
    """仅从 callback/job kwargs 重建完整 ScheduledTask。

    供 APS 回调使用：DateTrigger 到期后 job 可能已被移除，不能再 get_task。
    trigger_config 来源为 kwargs["trigger_config"]（lenient），无旧格式回退。
    """
    if not isinstance(kwargs, Mapping):
        raise SchedulerJobDecodeError("job kwargs is not a mapping", job_id=job_id)

    task_id = kwargs.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        if isinstance(job_id, str) and job_id:
            task_id = job_id
        else:
            raise SchedulerJobDecodeError("missing task_id", job_id=job_id)

    try:
        jkw = _JobKwargs.model_validate(kwargs)
        trigger_config = _TRIGGER_ADAPTER.validate_python(jkw.trigger_config)
    except ValidationError as exc:
        raise SchedulerJobDecodeError(
            f"job kwargs/trigger_config decode failed: {exc}",
            job_id=task_id,
            cause=exc,
        ) from exc

    return to_scheduled_task(
        jkw,
        task_id=task_id,
        trigger_config=trigger_config,
        enabled=enabled,
        next_run_time=next_run_time,
        normalize=None,
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

    与 decode_scheduled_task_from_kwargs 共享 _JobKwargs + to_scheduled_task。
    触发器来源保持不变：仍读 live APS trigger（decode_trigger），不切到
    kwargs["trigger_config"]（Tier-2，需先迁移，否则破坏 legacy all-zero-interval）。
    """
    job_id = getattr(job, "id", None)
    task_id = str(job_id) if job_id is not None else ""
    kwargs = getattr(job, "kwargs", None) or {}
    if not isinstance(kwargs, Mapping):
        raise SchedulerJobDecodeError("job kwargs is not a mapping", job_id=job_id)

    try:
        jkw = _JobKwargs.model_validate(kwargs)
    except ValidationError as exc:
        raise SchedulerJobDecodeError(
            f"job kwargs/trigger_config decode failed: {exc}",
            job_id=job_id,
            cause=exc,
        ) from exc

    try:
        _trigger_type, trigger_config = decode_trigger(getattr(job, "trigger", None))
    except Exception as exc:
        raise SchedulerJobDecodeError(
            f"trigger decode failed: {exc}",
            job_id=job_id,
            cause=exc,
        ) from exc

    next_run_time = getattr(job, "next_run_time", None)
    return to_scheduled_task(
        jkw,
        task_id=task_id,
        trigger_config=trigger_config,
        enabled=next_run_time is not None,
        next_run_time=next_run_time,
        normalize=normalize,
    )
