"""Unit tests for services.native_cron pure functions."""

from __future__ import annotations

import pytest

from services.native_cron import (
    NativeCron,
    aps_dow_to_unix,
    parse_native_cron,
    to_crontab_line,
    to_launchd_calendar,
    to_schtasks,
    unix_dow_to_aps,
)


# ---------------------------------------------------------------------------
# parse_native_cron — accept matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 9 * * *", NativeCron(minute=0, hour=9, day=None, month=None, dow=None)),
        ("30 8 1 * *", NativeCron(minute=30, hour=8, day=1, month=None, dow=None)),
        ("0 9 * * 1", NativeCron(minute=0, hour=9, day=None, month=None, dow=1)),
        ("45 * * * *", NativeCron(minute=45, hour=None, day=None, month=None, dow=None)),
        ("0 0 1 1 *", NativeCron(minute=0, hour=0, day=1, month=1, dow=None)),
        ("0 12 * * 0", NativeCron(minute=0, hour=12, day=None, month=None, dow=0)),
        ("0 12 * * 7", NativeCron(minute=0, hour=12, day=None, month=None, dow=0)),
    ],
)
def test_parse_accept(expr: str, expected: NativeCron):
    assert parse_native_cron(expr) == expected


# ---------------------------------------------------------------------------
# parse_native_cron — reject matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "0 9,10 * * *",  # list
        "0 9-17 * * *",  # range
        "*/5 * * * *",  # step (minute also *)
        "* 9 * * *",  # minute must be concrete
        "0 9 1 * 1",  # day + dow both restricted
        "0 9 * 3 1",  # dow + month restricted
        "0 25 * * *",  # hour out of range
        "60 9 * * *",  # minute out of range
        "0 9 32 * *",  # day out of range
        "0 9 * 13 *",  # month out of range
        "0 9 * * 8",  # dow out of range
        "0 9 * *",  # not 5 fields
        "0 9 * * * *",  # too many fields
        "0 mon * * *",  # name token
        "0 9 * * mon",  # dow name
    ],
)
def test_parse_reject(expr: str):
    with pytest.raises(ValueError):
        parse_native_cron(expr)


def test_parse_reject_messages_are_chinese():
    with pytest.raises(ValueError, match="minute") as ei:
        parse_native_cron("* 9 * * *")
    assert any("\u4e00" <= ch <= "\u9fff" for ch in str(ei.value))


# ---------------------------------------------------------------------------
# Platform translation
# ---------------------------------------------------------------------------


def test_to_schtasks_daily():
    spec = to_schtasks(parse_native_cron("0 9 * * *"))
    assert spec.schedule == "DAILY"
    assert spec.start_time == "09:00"
    assert spec.day_of_week is None
    assert spec.day_of_month is None
    assert spec.months is None


def test_to_schtasks_weekly():
    spec = to_schtasks(parse_native_cron("0 9 * * 1"))
    assert spec.schedule == "WEEKLY"
    assert spec.start_time == "09:00"
    assert spec.day_of_week == "MON"


def test_to_schtasks_weekly_sunday():
    spec = to_schtasks(parse_native_cron("0 12 * * 0"))
    assert spec.schedule == "WEEKLY"
    assert spec.day_of_week == "SUN"


def test_to_schtasks_monthly():
    spec = to_schtasks(parse_native_cron("30 8 1 * *"))
    assert spec.schedule == "MONTHLY"
    assert spec.start_time == "08:30"
    assert spec.day_of_month == 1
    assert spec.months is None


def test_to_schtasks_monthly_with_month():
    spec = to_schtasks(parse_native_cron("0 0 1 1 *"))
    assert spec.schedule == "MONTHLY"
    assert spec.start_time == "00:00"
    assert spec.day_of_month == 1
    assert spec.months == "JAN"


def test_to_schtasks_hourly():
    spec = to_schtasks(parse_native_cron("45 * * * *"))
    assert spec.schedule == "HOURLY"
    assert spec.start_time == "00:45"


def test_to_launchd_calendar_daily():
    assert to_launchd_calendar(parse_native_cron("0 9 * * *")) == {
        "Minute": 0,
        "Hour": 9,
    }


def test_to_launchd_calendar_weekly():
    assert to_launchd_calendar(parse_native_cron("0 9 * * 1")) == {
        "Minute": 0,
        "Hour": 9,
        "Weekday": 1,
    }


def test_to_launchd_calendar_monthly_with_month():
    assert to_launchd_calendar(parse_native_cron("0 0 1 1 *")) == {
        "Minute": 0,
        "Hour": 0,
        "Day": 1,
        "Month": 1,
    }


def test_to_launchd_calendar_hourly():
    assert to_launchd_calendar(parse_native_cron("45 * * * *")) == {"Minute": 45}


def test_to_launchd_calendar_sunday_unix():
    assert to_launchd_calendar(parse_native_cron("0 12 * * 0"))["Weekday"] == 0


def test_to_crontab_line_round_trip():
    for expr in (
        "0 9 * * *",
        "30 8 1 * *",
        "0 9 * * 1",
        "45 * * * *",
        "0 0 1 1 *",
        "0 12 * * 0",
    ):
        assert to_crontab_line(parse_native_cron(expr)) == expr


def test_to_crontab_line_normalizes_dow_7():
    assert to_crontab_line(parse_native_cron("0 12 * * 7")) == "0 12 * * 0"


# ---------------------------------------------------------------------------
# DOW mapping round-trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unix_dow", range(7))
def test_unix_aps_dow_round_trip(unix_dow: int):
    aps = unix_dow_to_aps(unix_dow)
    assert aps_dow_to_unix(aps) == unix_dow


def test_unix_dow_to_aps_known_values():
    # Unix 0=Sun → APS 6; Unix 1=Mon → APS 0
    assert unix_dow_to_aps(0) == 6
    assert unix_dow_to_aps(1) == 0
    assert unix_dow_to_aps(6) == 5
    assert aps_dow_to_unix(6) == 0
    assert aps_dow_to_unix(0) == 1
