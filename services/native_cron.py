"""原生 OS 调度用 cron 解析/校验/转换（纯函数）。

星期语义为 Unix：0 与 7 = 周日；APS 侧为 0 = 周一。
"""

from __future__ import annotations

from dataclasses import dataclass


_DOW_TO_SCHTASKS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
_MONTH_TO_SCHTASKS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


@dataclass(frozen=True)
class NativeCron:
    """解析后的严格单值 5 字段 cron，供原生 OS 注册。"""

    minute: int  # 必须为具体数值
    hour: int | None  # None 表示 *
    day: int | None
    month: int | None
    dow: int | None  # Unix 0-6；7 已归一为 0


@dataclass(frozen=True)
class SchtasksSpec:
    """Windows schtasks 调度参数。"""

    schedule: str  # DAILY / WEEKLY / MONTHLY / HOURLY
    start_time: str  # HH:MM
    day_of_week: str | None = None  # MON..SUN
    day_of_month: int | None = None
    months: str | None = None  # JAN..DEC；None 表示全年


def unix_dow_to_aps(dow: int) -> int:
    """Unix cron 星期（0=周日）→ APS 星期（0=周一）。"""
    return (dow - 1) % 7


def aps_dow_to_unix(dow: int) -> int:
    """APS 星期（0=周一）→ Unix cron 星期（0=周日）。"""
    return (dow + 1) % 7


def _parse_field(name: str, raw: str, lo: int, hi: int) -> int | None:
    """解析单字段：仅允许 ``*`` 或范围内单个整数（有意不支持 list/range/step/名称）。"""
    if raw == "*":
        return None
    if not raw.isdigit():
        raise ValueError(
            f"原生 cron 字段 {name} 仅允许 '*' 或单个数值，"
            f"不支持 list/range/step/名称: {raw!r}"
        )
    value = int(raw)
    if value < lo or value > hi:
        raise ValueError(f"原生 cron 字段 {name} 超出范围 [{lo}, {hi}]: {value}")
    return value


def parse_native_cron(cron: str) -> NativeCron:
    """解析并校验原生唤醒 cron（严格单值，供 OS 定时器注册）。

    约束：5 字段；每字段仅 ``*`` 或单整数；minute 必须具体；
    day 与 dow 不可同时受限；dow 受限时 day/month 须为 ``*``；
    dow=7 归一为 0。
    """
    if not isinstance(cron, str) or not cron.strip():
        raise ValueError("原生 cron 表达式不能为空")

    parts = cron.split()
    if len(parts) != 5:
        raise ValueError(f"原生 cron 必须为 5 字段，实际为 {len(parts)} 字段: {cron!r}")

    minute_raw, hour_raw, day_raw, month_raw, dow_raw = parts

    minute = _parse_field("minute", minute_raw, 0, 59)
    if minute is None:
        raise ValueError("原生 cron 的 minute 必须为具体数值，不能为 '*'")

    hour = _parse_field("hour", hour_raw, 0, 23)
    day = _parse_field("day", day_raw, 1, 31)
    month = _parse_field("month", month_raw, 1, 12)
    dow = _parse_field("dow", dow_raw, 0, 7)

    if dow is not None and dow == 7:
        dow = 0

    if day is not None and dow is not None:
        raise ValueError("原生 cron 不允许 day 与 day-of-week 同时受限")

    if dow is not None and (day is not None or month is not None):
        # day 与 dow 同时受限已在上方拒绝；此处主要拦截 month 受限
        raise ValueError("原生 cron 在 day-of-week 受限时，day 与 month 必须为 '*'")

    return NativeCron(minute=minute, hour=hour, day=day, month=month, dow=dow)


def to_schtasks(cron: NativeCron) -> SchtasksSpec:
    """NativeCron → Windows schtasks 调度参数。"""
    minute = cron.minute
    if cron.hour is None:
        return SchtasksSpec(
            schedule="HOURLY",
            start_time=f"00:{minute:02d}",
        )

    start_time = f"{cron.hour:02d}:{minute:02d}"

    if cron.dow is not None:
        return SchtasksSpec(
            schedule="WEEKLY",
            start_time=start_time,
            day_of_week=_DOW_TO_SCHTASKS[cron.dow],
        )

    if cron.day is not None:
        months = None
        if cron.month is not None:
            months = _MONTH_TO_SCHTASKS[cron.month - 1]
        return SchtasksSpec(
            schedule="MONTHLY",
            start_time=start_time,
            day_of_month=cron.day,
            months=months,
        )

    return SchtasksSpec(schedule="DAILY", start_time=start_time)


def to_launchd_calendar(cron: NativeCron) -> dict[str, int]:
    """NativeCron → launchd StartCalendarInterval（``*`` 字段省略；Weekday 为 Unix 语义）。"""
    result: dict[str, int] = {"Minute": cron.minute}
    if cron.hour is not None:
        result["Hour"] = cron.hour
    if cron.day is not None:
        result["Day"] = cron.day
    if cron.month is not None:
        result["Month"] = cron.month
    if cron.dow is not None:
        result["Weekday"] = cron.dow
    return result


def to_crontab_line(cron: NativeCron) -> str:
    """NativeCron 序列化为 5 字段 crontab 行（通配写 ``*``）。"""

    def fmt(value: int | None) -> str:
        return "*" if value is None else str(value)

    return (
        f"{cron.minute} {fmt(cron.hour)} {fmt(cron.day)} "
        f"{fmt(cron.month)} {fmt(cron.dow)}"
    )
