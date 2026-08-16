"""严格的原生 cron 解析与跨平台转换（纯函数，无 I/O）。

供系统级调度（schtasks / launchctl / crontab）使用的 cron 子集：
5 个字段、单值语义（不支持列表/范围/步进），分钟必须具体。
"""

from dataclasses import dataclass

# 字段中文名，用于报错信息
_FIELD_NAMES = ("分钟", "小时", "日", "月", "星期")

# 各字段取值范围
_FIELD_RANGES = (
    (0, 59),  # 分钟
    (0, 23),  # 小时
    (1, 31),  # 日
    (1, 12),  # 月
    (0, 7),  # 星期（Unix 约定，0 和 7 均为周日）
)

# Unix 星期（0=周日）→ schtasks 三字母英文缩写
_SCHTASKS_DOW = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")

# 月份 1-12 → 三字母英文缩写
_SCHTASKS_MONTHS = (
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
    """严格 cron 表达式的解析结果。

    minute 必填；其余字段为 None 表示 ``*``。dow 采用 Unix 约定（0=周日），
    解析时已将 7 归一化为 0。
    """

    minute: int
    hour: int | None
    day: int | None
    month: int | None
    dow: int | None


def parse_native_cron(cron: str) -> NativeCron:
    """解析严格 cron 表达式（5 字段，单值语义），失败抛出 ValueError。

    规则：
    - 必须恰好 5 个空白分隔字段：分钟 小时 日 月 星期。
    - 每个字段为 ``*`` 或单个具体整数（分钟 0-59、小时 0-23、日 1-31、月 1-12、星期 0-7）；
      不支持列表（``1,2``）、范围（``1-5``）、步进（``*/2``）。
    - 分钟必须为具体数值。
    - 日与星期不得同时受限。
    - 小时为 ``*`` 时，日、月、星期必须全为 ``*``。
    - 月受限时，日必须同时受限。
    - 星期 7 归一化为 0。
    """
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(
            f"cron 表达式必须包含 5 个字段（分钟 小时 日 月 星期），"
            f"实际为 {len(fields)} 个：{cron!r}"
        )

    values: list[int | None] = []
    for index, field in enumerate(fields):
        if field == "*":
            values.append(None)
            continue
        if not field.isdigit():
            raise ValueError(
                f"{_FIELD_NAMES[index]}字段无效：{field!r}（仅支持 * 或单个具体数值）"
            )
        value = int(field)
        low, high = _FIELD_RANGES[index]
        if not low <= value <= high:
            raise ValueError(
                f"{_FIELD_NAMES[index]}字段超出范围：{value}（允许 {low}-{high}）"
            )
        values.append(value)

    minute, hour, day, month, dow = values

    if minute is None:
        raise ValueError("分钟字段必须为具体数值，不能为 *（避免每小时重复触发）")

    if day is not None and dow is not None:
        raise ValueError("日与星期字段不得同时受限（cron 语义冲突）")

    if hour is None and (day is not None or month is not None or dow is not None):
        raise ValueError("小时为 * 时，日、月、星期必须全部为 *")

    if month is not None and day is None:
        raise ValueError("月字段受限时，日字段必须同时受限")

    # 星期 7（=周日）归一化为 0
    if dow == 7:
        dow = 0

    return NativeCron(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        dow=dow,
    )


def to_schtasks_args(nc: NativeCron) -> list[str]:
    """转换为 ``schtasks /Create`` 的调度参数段（``/SC`` 之后的部分）。

    映射规则（选择最简单且正确的组合）：
    - 仅分钟受限（hour 为 None）→ ``/SC HOURLY /ST 00:MM``，每小时在该分钟触发。
    - 小时受限、无日/星期/月 → ``/SC DAILY /ST HH:MM``。
    - 星期受限 → ``/SC WEEKLY /ST HH:MM /D DOW``（三字母英文，Unix 0=周日）。
    - 月与日同时受限 → ``/SC MONTHLY /ST HH:MM /D day /M MON``（三字母英文月份）。
    - 仅日受限（无月）→ ``/SC MONTHLY /ST HH:MM /D day``（schtasks 缺省每月执行）。
    """
    if nc.hour is None:
        return ["/SC", "HOURLY", "/ST", f"00:{nc.minute:02d}"]

    start = f"{nc.hour:02d}:{nc.minute:02d}"
    if nc.dow is not None:
        return ["/SC", "WEEKLY", "/ST", start, "/D", _SCHTASKS_DOW[nc.dow]]
    if nc.month is not None:
        assert nc.day is not None  # 解析规则保证
        return [
            "/SC",
            "MONTHLY",
            "/ST",
            start,
            "/D",
            str(nc.day),
            "/M",
            _SCHTASKS_MONTHS[nc.month - 1],
        ]
    if nc.day is not None:
        return ["/SC", "MONTHLY", "/ST", start, "/D", str(nc.day)]
    return ["/SC", "DAILY", "/ST", start]


def to_launchd_calendar(nc: NativeCron) -> dict[str, int]:
    """转换为 launchd ``StartCalendarInterval`` 字典。

    ``Minute`` 恒有；``Hour``/``Day``/``Month``/``Weekday`` 仅在该字段受限时出现
    （launchd 省略字段表示任意值，与 cron 的 ``*`` 对应）。
    """
    calendar: dict[str, int] = {"Minute": nc.minute}
    if nc.hour is not None:
        calendar["Hour"] = nc.hour
    if nc.day is not None:
        calendar["Day"] = nc.day
    if nc.month is not None:
        calendar["Month"] = nc.month
    if nc.dow is not None:
        # launchd 与 Unix 同为 0/7=周日；解析后 dow 已归一化为 0-6
        calendar["Weekday"] = nc.dow
    return calendar


def to_crontab_line(nc: NativeCron) -> str:
    """转换为标准 crontab 5 字段行；None 写 ``*``，星期 0 写 ``0``。"""
    return " ".join(
        str(value) if value is not None else "*"
        for value in (nc.minute, nc.hour, nc.day, nc.month, nc.dow)
    )


def unix_dow_to_aps(dow: int) -> int:
    """Unix 星期（0=周日）→ APScheduler 星期（0=周一）。"""
    return (dow + 6) % 7


def aps_dow_to_unix(dow: int) -> int:
    """APScheduler 星期（0=周一）→ Unix 星期（0=周日）。"""
    return (dow + 1) % 7
