"""Native OS scheduler cron parse / validate / translate (pure functions).

Unix day-of-week semantics: 0 and 7 = Sunday. APS uses 0 = Monday.
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
    """Parsed single-value 5-field cron for native OS registration."""

    minute: int  # required concrete value
    hour: int | None  # None = *
    day: int | None
    month: int | None
    dow: int | None  # Unix 0-6, 7 normalized to 0


@dataclass(frozen=True)
class SchtasksSpec:
    """Windows schtasks schedule parameters."""

    schedule: str  # DAILY / WEEKLY / MONTHLY / HOURLY
    start_time: str  # HH:MM
    day_of_week: str | None = None  # MON..SUN
    day_of_month: int | None = None
    months: str | None = None  # JAN..DEC or None for all


def unix_dow_to_aps(dow: int) -> int:
    """Unix cron DOW (0=Sunday) → APScheduler DOW (0=Monday)."""
    return (dow - 1) % 7


def aps_dow_to_unix(dow: int) -> int:
    """APScheduler DOW (0=Monday) → Unix cron DOW (0=Sunday)."""
    return (dow + 1) % 7


def _parse_field(name: str, raw: str, lo: int, hi: int) -> int | None:
    """Parse one cron field: only ``*`` or a single integer in range."""
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
    """Parse and validate a native-wakeup cron expression.

    Rules:
    - exactly 5 fields
    - each field is ``*`` or a single integer (no list/range/step/names)
    - minute must be a concrete integer
    - day and dow must not both be restricted
    - when dow is restricted, day and month must be ``*``
    - ranges: minute 0-59, hour 0-23, day 1-31, month 1-12, dow 0-7
    - dow 7 is normalized to 0 (Sunday)
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
        # day already rejected above when both set; month must be * when dow set
        raise ValueError("原生 cron 在 day-of-week 受限时，day 与 month 必须为 '*'")

    return NativeCron(minute=minute, hour=hour, day=day, month=month, dow=dow)


def to_schtasks(cron: NativeCron) -> SchtasksSpec:
    """Translate NativeCron to Windows schtasks schedule parameters."""
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
    """Translate NativeCron to launchd StartCalendarInterval dict.

    ``*`` fields are omitted. Weekday uses Unix semantics (0=Sunday),
    matching launchd.
    """
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
    """Serialize NativeCron back to a 5-field crontab line (``*`` for wildcards)."""

    def fmt(value: int | None) -> str:
        return "*" if value is None else str(value)

    return (
        f"{cron.minute} {fmt(cron.hour)} {fmt(cron.day)} "
        f"{fmt(cron.month)} {fmt(cron.dow)}"
    )
