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
# parse_native_cron — representative accept / reject
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 9 * * *", NativeCron(minute=0, hour=9, day=None, month=None, dow=None)),
        ("30 8 1 * *", NativeCron(minute=30, hour=8, day=1, month=None, dow=None)),
        ("0 9 * * 1", NativeCron(minute=0, hour=9, day=None, month=None, dow=1)),
        (
            "45 * * * *",
            NativeCron(minute=45, hour=None, day=None, month=None, dow=None),
        ),
        ("0 0 1 1 *", NativeCron(minute=0, hour=0, day=1, month=1, dow=None)),
        ("0 12 * * 0", NativeCron(minute=0, hour=12, day=None, month=None, dow=0)),
        ("0 12 * * 7", NativeCron(minute=0, hour=12, day=None, month=None, dow=0)),
    ],
)
def test_parse_accept(expr: str, expected: NativeCron):
    assert parse_native_cron(expr) == expected


@pytest.mark.parametrize(
    "expr",
    [
        "0 9,10 * * *",  # list
        "*/5 * * * *",  # step
        "* 9 * * *",  # minute must be concrete
        "0 9 1 * 1",  # day + dow both restricted
        "0 25 * * *",  # hour out of range
        "0 9 * * 8",  # dow out of range
        "0 9 * *",  # not 5 fields
        "0 mon * * *",  # name token
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
# Platform translation — one representative per schedule shape
# ---------------------------------------------------------------------------


def test_to_schtasks_shapes():
    daily = to_schtasks(parse_native_cron("0 9 * * *"))
    assert daily.schedule == "DAILY"
    assert daily.start_time == "09:00"

    weekly = to_schtasks(parse_native_cron("0 9 * * 1"))
    assert weekly.schedule == "WEEKLY"
    assert weekly.day_of_week == "MON"

    weekly_sun = to_schtasks(parse_native_cron("0 12 * * 0"))
    assert weekly_sun.day_of_week == "SUN"

    monthly = to_schtasks(parse_native_cron("30 8 1 * *"))
    assert monthly.schedule == "MONTHLY"
    assert monthly.day_of_month == 1

    monthly_jan = to_schtasks(parse_native_cron("0 0 1 1 *"))
    assert monthly_jan.months == "JAN"

    hourly = to_schtasks(parse_native_cron("45 * * * *"))
    assert hourly.schedule == "HOURLY"
    assert hourly.start_time == "00:45"


def test_to_launchd_calendar_shapes():
    assert to_launchd_calendar(parse_native_cron("0 9 * * *")) == {
        "Minute": 0,
        "Hour": 9,
    }
    assert to_launchd_calendar(parse_native_cron("0 9 * * 1")) == {
        "Minute": 0,
        "Hour": 9,
        "Weekday": 1,
    }
    assert to_launchd_calendar(parse_native_cron("0 0 1 1 *")) == {
        "Minute": 0,
        "Hour": 0,
        "Day": 1,
        "Month": 1,
    }
    assert to_launchd_calendar(parse_native_cron("45 * * * *")) == {"Minute": 45}
    assert to_launchd_calendar(parse_native_cron("0 12 * * 0"))["Weekday"] == 0


def test_to_crontab_line_round_trip_and_dow_7():
    for expr in ("0 9 * * *", "30 8 1 * *", "0 9 * * 1", "45 * * * *", "0 12 * * 0"):
        assert to_crontab_line(parse_native_cron(expr)) == expr
    assert to_crontab_line(parse_native_cron("0 12 * * 7")) == "0 12 * * 0"


# ---------------------------------------------------------------------------
# DOW mapping — boundary values only (not exhaustive range)
# ---------------------------------------------------------------------------


def test_unix_aps_dow_boundary_mapping():
    # Unix 0=Sun → APS 6; Unix 1=Mon → APS 0; Unix 6=Sat → APS 5
    assert unix_dow_to_aps(0) == 6
    assert unix_dow_to_aps(1) == 0
    assert unix_dow_to_aps(6) == 5
    assert aps_dow_to_unix(6) == 0
    assert aps_dow_to_unix(0) == 1
