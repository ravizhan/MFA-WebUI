"""Tests for services/native_cron.py — strict native cron parsing and OS conversion."""

import pytest

from services.native_cron import (
    NativeCron,
    aps_dow_to_unix,
    parse_native_cron,
    to_crontab_line,
    to_launchd_calendar,
    to_schtasks_args,
    unix_dow_to_aps,
)


# ---------------------------------------------------------------------------
# parse_native_cron — accept matrix
# ---------------------------------------------------------------------------


class TestParseNativeCronAccepts:
    @pytest.mark.parametrize(
        ("cron", "expected"),
        [
            # 每日 09:00
            ("0 9 * * *", NativeCron(minute=0, hour=9, day=None, month=None, dow=None)),
            # 每小时第 5 分钟（分钟必须具体）
            (
                "5 * * * *",
                NativeCron(minute=5, hour=None, day=None, month=None, dow=None),
            ),
            # 每周日 14:30（dow 7 → 0）
            (
                "30 14 * * 7",
                NativeCron(minute=30, hour=14, day=None, month=None, dow=0),
            ),
            # 每周日（dow 0 保持 0）
            ("0 9 * * 0", NativeCron(minute=0, hour=9, day=None, month=None, dow=0)),
            # 每周一 09:00
            ("0 9 * * 1", NativeCron(minute=0, hour=9, day=None, month=None, dow=1)),
            # 每月 15 日 09:00（仅日受限）
            ("0 9 15 * *", NativeCron(minute=0, hour=9, day=15, month=None, dow=None)),
            # 每年 3 月 15 日 09:00（月 + 日同时受限）
            ("0 9 15 3 *", NativeCron(minute=0, hour=9, day=15, month=3, dow=None)),
            # 月 + 日全具体：12-31 23:59
            (
                "59 23 31 12 *",
                NativeCron(minute=59, hour=23, day=31, month=12, dow=None),
            ),
            # 仅星期受限的全具体形式：周六 23:59
            (
                "59 23 * * 6",
                NativeCron(minute=59, hour=23, day=None, month=None, dow=6),
            ),
        ],
    )
    def test_accepts(self, cron, expected):
        assert parse_native_cron(cron) == expected


# ---------------------------------------------------------------------------
# parse_native_cron — reject matrix
# ---------------------------------------------------------------------------


class TestParseNativeCronRejects:
    @pytest.mark.parametrize(
        "cron",
        [
            "0 9 * *",  # 4 个字段
            "0 9 * * * *",  # 6 个字段
            "",  # 空
        ],
    )
    def test_wrong_field_count(self, cron):
        with pytest.raises(ValueError, match="5 个字段"):
            parse_native_cron(cron)

    @pytest.mark.parametrize(
        "cron",
        [
            "0,30 9 * * *",  # 列表
            "0 9 1-5 * *",  # 范围
            "*/5 9 * * *",  # 步进
            "x 9 * * *",  # 非数字
            "0 9 * * MON",  # 名称
            "0 9 * * -1",  # 负数（非数字）
        ],
    )
    def test_non_single_value(self, cron):
        with pytest.raises(ValueError):
            parse_native_cron(cron)

    def test_minute_must_be_concrete(self):
        with pytest.raises(ValueError, match="分钟字段必须为具体数值"):
            parse_native_cron("* 9 * * *")

    @pytest.mark.parametrize(
        "cron",
        [
            "60 9 * * *",  # 分钟越界
            "0 24 * * *",  # 小时越界
            "0 9 0 * *",  # 日越界（1-31）
            "0 9 32 * *",  # 日越界
            "0 9 * 0 *",  # 月越界（1-12）
            "0 9 * 13 *",  # 月越界
            "0 9 * * 8",  # 星期越界（0-7）
        ],
    )
    def test_out_of_range(self, cron):
        with pytest.raises(ValueError, match="超出范围"):
            parse_native_cron(cron)

    @pytest.mark.parametrize(
        "cron",
        [
            "0 9 15 * 1",  # 日与星期同时受限
            "0 9 15 3 1",
        ],
    )
    def test_day_and_dow_conflict(self, cron):
        with pytest.raises(ValueError, match="日与星期字段不得同时受限"):
            parse_native_cron(cron)

    @pytest.mark.parametrize(
        "cron",
        [
            "0 * 15 * *",  # hour=* 但日受限
            "0 * * 3 *",  # hour=* 但月受限
            "0 * * * 1",  # hour=* 但星期受限
        ],
    )
    def test_hour_star_requires_all_star(self, cron):
        with pytest.raises(ValueError, match="小时为 \\* 时"):
            parse_native_cron(cron)

    @pytest.mark.parametrize(
        "cron",
        [
            "0 9 * 3 *",  # 月受限但日未受限
            "30 14 * 3 *",
        ],
    )
    def test_month_requires_day(self, cron):
        with pytest.raises(ValueError, match="月字段受限时"):
            parse_native_cron(cron)


# ---------------------------------------------------------------------------
# to_schtasks_args
# ---------------------------------------------------------------------------


class TestToSchtasksArgs:
    def test_daily(self):
        assert to_schtasks_args(parse_native_cron("0 9 * * *")) == [
            "/SC",
            "DAILY",
            "/ST",
            "09:00",
        ]

    def test_hourly_minute_only(self):
        assert to_schtasks_args(parse_native_cron("5 * * * *")) == [
            "/SC",
            "HOURLY",
            "/ST",
            "00:05",
        ]

    def test_weekly_dow7_normalized_to_sun(self):
        assert to_schtasks_args(parse_native_cron("30 14 * * 7")) == [
            "/SC",
            "WEEKLY",
            "/ST",
            "14:30",
            "/D",
            "SUN",
        ]

    def test_weekly_dow1_is_mon(self):
        assert to_schtasks_args(parse_native_cron("0 9 * * 1")) == [
            "/SC",
            "WEEKLY",
            "/ST",
            "09:00",
            "/D",
            "MON",
        ]

    def test_monthly_with_month(self):
        assert to_schtasks_args(parse_native_cron("0 9 15 3 *")) == [
            "/SC",
            "MONTHLY",
            "/ST",
            "09:00",
            "/D",
            "15",
            "/M",
            "MAR",
        ]

    def test_monthly_day_only(self):
        assert to_schtasks_args(parse_native_cron("0 9 15 * *")) == [
            "/SC",
            "MONTHLY",
            "/ST",
            "09:00",
            "/D",
            "15",
        ]


# ---------------------------------------------------------------------------
# to_launchd_calendar
# ---------------------------------------------------------------------------


class TestToLaunchdCalendar:
    def test_daily_has_minute_and_hour_only(self):
        calendar = to_launchd_calendar(parse_native_cron("0 9 * * *"))
        assert calendar == {"Minute": 0, "Hour": 9}
        assert "Day" not in calendar
        assert "Month" not in calendar
        assert "Weekday" not in calendar

    def test_hourly_has_minute_only(self):
        calendar = to_launchd_calendar(parse_native_cron("5 * * * *"))
        assert calendar == {"Minute": 5}
        assert "Hour" not in calendar

    def test_weekly_has_weekday(self):
        calendar = to_launchd_calendar(parse_native_cron("30 14 * * 1"))
        assert calendar == {"Minute": 30, "Hour": 14, "Weekday": 1}

    def test_monthly_has_day_and_month(self):
        calendar = to_launchd_calendar(parse_native_cron("0 9 15 3 *"))
        assert calendar == {"Minute": 0, "Hour": 9, "Day": 15, "Month": 3}
        assert "Weekday" not in calendar


# ---------------------------------------------------------------------------
# to_crontab_line — round-trip
# ---------------------------------------------------------------------------


class TestToCrontabLine:
    @pytest.mark.parametrize(
        ("cron", "expected"),
        [
            ("0 9 * * *", "0 9 * * *"),
            ("5 * * * *", "5 * * * *"),
            ("59 23 31 12 *", "59 23 31 12 *"),
            # dow 7 归一化为 0
            ("30 14 * * 7", "30 14 * * 0"),
        ],
    )
    def test_round_trip(self, cron, expected):
        assert to_crontab_line(parse_native_cron(cron)) == expected


# ---------------------------------------------------------------------------
# unix_dow_to_aps / aps_dow_to_unix round-trip
# ---------------------------------------------------------------------------


class TestDowConversion:
    @pytest.mark.parametrize("dow", list(range(7)))
    def test_round_trip(self, dow):
        assert aps_dow_to_unix(unix_dow_to_aps(dow)) == dow

    def test_unix_sunday_to_aps_saturday(self):
        assert unix_dow_to_aps(0) == 6

    def test_unix_monday_to_aps_monday_zero(self):
        assert unix_dow_to_aps(1) == 0

    def test_aps_monday_zero_to_unix_monday_one(self):
        assert aps_dow_to_unix(0) == 1
