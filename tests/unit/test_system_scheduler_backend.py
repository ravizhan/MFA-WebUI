"""系统级调度后端单元测试。

测试覆盖：
- validate_task_id: UUID 格式校验
- _parse_cron_fields: 5-field cron 解析
- map_trigger_to_os_spec: 触发器映射（Cron/Date/Interval）
- 不支持模式的拒绝
"""

import re
from datetime import datetime, timedelta

import pytest

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
)
from services.system_scheduler_backend import (
    _parse_cron_field_list,
    _parse_cron_fields,
    map_trigger_to_os_spec,
    validate_task_id,
)


# ---------------------------------------------------------------------------
# validate_task_id
# ---------------------------------------------------------------------------


class TestValidateTaskId:
    """task_id UUID 格式校验测试"""

    def test_valid_uuid(self):
        validate_task_id("550e8400-e29b-41d4-a716-446655440000")

    def test_valid_uuid_uppercase_rejected(self):
        # UUID 必须是小写十六进制
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("550E8400-E29B-41D4-A716-446655440000")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("")

    def test_random_string(self):
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("not-a-uuid")

    def test_command_injection_attempt(self):
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("; rm -rf /")

    def test_path_traversal_attempt(self):
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("../../../etc/passwd")


# ---------------------------------------------------------------------------
# _parse_cron_fields
# ---------------------------------------------------------------------------


class TestParseCronFields:
    """5-field cron 表达式解析测试"""

    def test_basic_cron(self):
        result = _parse_cron_fields("0 9 * * *")
        assert result["minute"] == "0"
        assert result["hour"] == "9"
        assert result["day"] == "*"
        assert result["month"] == "*"
        assert result["weekday"] == "*"

    def test_all_wildcards(self):
        result = _parse_cron_fields("* * * * *")
        assert all(v == "*" for v in result.values())

    def test_complex_cron(self):
        result = _parse_cron_fields("*/5 8-18 1,15 * 1-5")
        assert result["minute"] == "*/5"
        assert result["hour"] == "8-18"
        assert result["day"] == "1,15"
        assert result["month"] == "*"
        assert result["weekday"] == "1-5"

    def test_extra_whitespace(self):
        result = _parse_cron_fields("  0   9   *   *   *  ")
        assert result["minute"] == "0"
        assert result["hour"] == "9"

    def test_too_few_fields(self):
        with pytest.raises(ValueError, match="无效的 cron 表达式"):
            _parse_cron_fields("0 9 * *")

    def test_too_many_fields(self):
        with pytest.raises(ValueError, match="无效的 cron 表达式"):
            _parse_cron_fields("0 9 * * * 0")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="无效的 cron 表达式"):
            _parse_cron_fields("")


# ---------------------------------------------------------------------------
# _parse_cron_field_list
# ---------------------------------------------------------------------------


class TestParseCronFieldList:
    """cron 字段值展开测试"""

    def test_wildcard(self):
        assert _parse_cron_field_list("*", 59) == list(range(60))

    def test_single_value(self):
        assert _parse_cron_field_list("5", 59) == [5]

    def test_comma_separated(self):
        assert _parse_cron_field_list("1,3,5", 59) == [1, 3, 5]

    def test_range(self):
        assert _parse_cron_field_list("1-5", 59) == [1, 2, 3, 4, 5]

    def test_step(self):
        assert _parse_cron_field_list("*/15", 59) == [0, 15, 30, 45]

    def test_step_from_value(self):
        assert _parse_cron_field_list("5/10", 59) == [5, 15, 25, 35, 45, 55]

    def test_mixed(self):
        result = _parse_cron_field_list("0,15,30-45/5", 59)
        assert 0 in result
        assert 15 in result
        assert 30 in result
        assert 35 in result
        assert 40 in result
        assert 45 in result

    def test_sorted(self):
        result = _parse_cron_field_list("5,1,3", 59)
        assert result == [1, 3, 5]

    def test_deduplicated(self):
        result = _parse_cron_field_list("1,1,1", 59)
        assert result == [1]


# ---------------------------------------------------------------------------
# map_trigger_to_os_spec
# ---------------------------------------------------------------------------


class TestMapTriggerToOsSpec:
    """触发器映射测试"""

    def test_cron_trigger(self):
        config = CronTriggerConfig(cron="0 9 * * *")
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "cron"
        assert spec.cron_expression == "0 9 * * *"
        assert spec.run_date is None
        assert spec.interval_minutes is None

    def test_date_trigger_future(self):
        future_date = datetime.now() + timedelta(days=1)
        config = DateTriggerConfig(run_date=future_date)
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "date"
        assert spec.run_date == future_date
        assert spec.cron_expression is None

    def test_date_trigger_past_rejected(self):
        past_date = datetime.now() - timedelta(days=1)
        config = DateTriggerConfig(run_date=past_date)
        with pytest.raises(ValueError, match="DateTrigger 已过期"):
            map_trigger_to_os_spec(config)

    def test_interval_trigger_minutes_only(self):
        config = IntervalTriggerConfig(minutes=30)
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "interval"
        assert spec.interval_minutes == 30

    def test_interval_trigger_hours(self):
        config = IntervalTriggerConfig(hours=2)
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "interval"
        assert spec.interval_minutes == 120

    def test_interval_trigger_days(self):
        config = IntervalTriggerConfig(days=1)
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "interval"
        assert spec.interval_minutes == 1440

    def test_interval_trigger_weeks(self):
        config = IntervalTriggerConfig(weeks=1)
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "interval"
        assert spec.interval_minutes == 7 * 24 * 60

    def test_interval_trigger_combined(self):
        config = IntervalTriggerConfig(weeks=1, days=1, hours=2, minutes=30)
        spec = map_trigger_to_os_spec(config)
        expected = 7 * 24 * 60 + 24 * 60 + 2 * 60 + 30
        assert spec.interval_minutes == expected

    def test_interval_trigger_seconds_rounds_up(self):
        config = IntervalTriggerConfig(minutes=5, seconds=30)
        spec = map_trigger_to_os_spec(config)
        # 5 minutes + 30 seconds → rounds up to 6 minutes
        assert spec.interval_minutes == 6

    def test_interval_trigger_seconds_only(self):
        config = IntervalTriggerConfig(seconds=30)
        spec = map_trigger_to_os_spec(config)
        # 30 seconds → rounds up to 1 minute (minimum)
        assert spec.interval_minutes == 1

    def test_interval_trigger_zero(self):
        config = IntervalTriggerConfig(minutes=0, hours=0)
        spec = map_trigger_to_os_spec(config)
        # All zeros → minimum 1 minute
        assert spec.interval_minutes == 1

    def test_interval_trigger_all_none(self):
        config = IntervalTriggerConfig()
        spec = map_trigger_to_os_spec(config)
        assert spec.interval_minutes == 1
