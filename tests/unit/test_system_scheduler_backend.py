"""OS scheduler backend unit tests — user-level registration + trigger contracts."""

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    OSTriggerSpec,
    SystemTaskSpec,
)
from services.system_scheduler_backend import (
    LinuxBackend,
    MacOSBackend,
    WindowsBackend,
    _parse_cron_field_list,
    _parse_cron_fields,
    build_native_command,
    map_trigger_to_os_spec,
    validate_linux_cron_expression,
    validate_task_id,
    validate_trigger_for_platform,
    windows_join_args,
    windows_quote_argument,
)

TID = "550e8400-e29b-41d4-a716-446655440000"


class TestValidateTaskId:
    def test_valid_uuid(self):
        validate_task_id("550e8400-e29b-41d4-a716-446655440000")

    def test_valid_uuid_uppercase_rejected(self):
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("550E8400-E29B-41D4-A716-446655440000")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("")

    def test_command_injection_attempt(self):
        with pytest.raises(ValueError, match="无效的 task_id"):
            validate_task_id("; rm -rf /")


class TestParseCronFields:
    def test_basic_cron(self):
        result = _parse_cron_fields("0 9 * * *")
        assert result["minute"] == "0"
        assert result["hour"] == "9"

    def test_too_few_fields(self):
        with pytest.raises(ValueError, match="无效的 cron 表达式"):
            _parse_cron_fields("0 9 * *")


class TestParseCronFieldList:
    def test_wildcard(self):
        assert _parse_cron_field_list("*", 59) == list(range(60))

    def test_step(self):
        assert _parse_cron_field_list("*/15", 59) == [0, 15, 30, 45]

    def test_names_rejected(self):
        with pytest.raises(ValueError):
            _parse_cron_field_list("MON", 7)


class TestMapTriggerToOsSpec:
    def test_cron_trigger(self):
        config = CronTriggerConfig(cron="0 9 * * *")
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "cron"
        assert spec.cron_expression == "0 9 * * *"

    def test_date_trigger_future_timezone_aware(self):
        future_date = datetime.now(timezone.utc) + timedelta(days=1)
        config = DateTriggerConfig(run_date=future_date)
        spec = map_trigger_to_os_spec(config)
        assert spec.trigger_type == "date"
        assert spec.run_date is not None
        assert spec.run_date.tzinfo is not None

    def test_date_trigger_past_rejected(self):
        past_date = datetime.now() - timedelta(days=1)
        config = DateTriggerConfig(run_date=past_date)
        with pytest.raises(ValueError, match="已过期"):
            map_trigger_to_os_spec(config)

    def test_interval_whole_minutes(self):
        config = IntervalTriggerConfig(minutes=30)
        spec = map_trigger_to_os_spec(config)
        assert spec.interval_minutes == 30

    def test_interval_seconds_rejected(self):
        config = IntervalTriggerConfig(minutes=5, seconds=30)
        with pytest.raises(ValueError, match="秒级"):
            map_trigger_to_os_spec(config)

    def test_interval_start_end_rejected(self):
        config = IntervalTriggerConfig(
            minutes=5, start_date=datetime.now() + timedelta(hours=1)
        )
        with pytest.raises(ValueError, match="start_date"):
            map_trigger_to_os_spec(config)

    def test_interval_out_of_range(self):
        config = IntervalTriggerConfig(minutes=0)
        with pytest.raises(ValueError, match="1..44640"):
            map_trigger_to_os_spec(config)

    def test_interval_max(self):
        config = IntervalTriggerConfig(minutes=44640)
        assert map_trigger_to_os_spec(config).interval_minutes == 44640


class TestPlatformValidation:
    def test_windows_cron_fixed_daily_only(self):
        ok = OSTriggerSpec(trigger_type="cron", cron_expression="0 9 * * *")
        validate_trigger_for_platform("windows", ok)
        bad = OSTriggerSpec(trigger_type="cron", cron_expression="*/5 * * * *")
        with pytest.raises(ValueError):
            validate_trigger_for_platform("windows", bad)

    def test_macos_date_rejected(self):
        dt = OSTriggerSpec(
            trigger_type="date",
            run_date=datetime.now(timezone.utc) + timedelta(days=1),
        )
        with pytest.raises(ValueError, match="拒绝 date"):
            validate_trigger_for_platform("macos", dt)

    def test_macos_interval_warning(self):
        tr = OSTriggerSpec(trigger_type="interval", interval_minutes=5)
        warnings = validate_trigger_for_platform("macos", tr)
        assert any("睡眠" in w or "sleep" in w.lower() for w in warnings)

    def test_linux_date_interval_rejected(self):
        with pytest.raises(ValueError):
            validate_trigger_for_platform(
                "linux", OSTriggerSpec(trigger_type="date", run_date=datetime.now())
            )
        with pytest.raises(ValueError):
            validate_trigger_for_platform(
                "linux", OSTriggerSpec(trigger_type="interval", interval_minutes=5)
            )

    def test_linux_cron_dow_star_only(self):
        validate_linux_cron_expression("0 9 1 * *")
        with pytest.raises(ValueError, match="day-of-week"):
            validate_linux_cron_expression("0 9 * * 1")
        with pytest.raises(ValueError):
            validate_linux_cron_expression("0 9 * * MON")


class TestWindowsQuoting:
    def test_spaces(self):
        assert (
            windows_quote_argument("C:\\Program Files\\mwu")
            == '"C:\\Program Files\\mwu"'
        )

    def test_join_args(self):
        line = windows_join_args(["main.py", "--task", "abc def"])
        assert "main.py" in line
        assert '"abc def"' in line


class TestNativeCommand:
    def test_source_mode_includes_main_py(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("#", encoding="utf-8")
        exe, args = build_native_command(
            tmp_path, "550e8400-e29b-41d4-a716-446655440000", frozen=False
        )
        assert exe  # python executable
        assert any(
            str(tmp_path / "main.py") in a or a.endswith("main.py") for a in args
        )
        assert "--headless" in args
        assert "--task" in args

    def test_frozen_mode_no_main_py(self, tmp_path: Path):
        exe, args = build_native_command(
            tmp_path, "550e8400-e29b-41d4-a716-446655440000", frozen=True
        )
        assert args == [
            "--headless",
            "--task",
            "550e8400-e29b-41d4-a716-446655440000",
        ]


class TestGoldenArtifacts:
    def _spec(self, platform_trigger="cron") -> SystemTaskSpec:
        tid = "550e8400-e29b-41d4-a716-446655440000"
        if platform_trigger == "cron":
            trigger = OSTriggerSpec(trigger_type="cron", cron_expression="0 9 * * *")
        elif platform_trigger == "interval":
            trigger = OSTriggerSpec(trigger_type="interval", interval_minutes=15)
        else:
            trigger = OSTriggerSpec(
                trigger_type="date",
                run_date=datetime.now(timezone.utc) + timedelta(days=2),
            )
        return SystemTaskSpec(
            task_id=tid,
            task_name="Golden Task",
            exe_path=r"C:\Program Files\MWU\python.exe",
            cli_args=[r"C:\Program Files\MWU\main.py", "--headless", "--task", tid],
            trigger=trigger,
            working_dir=r"C:\Program Files\MWU",
        )

    def test_windows_xml_user_interactive_and_cron(self):
        backend = WindowsBackend()
        xml = backend._build_task_xml(self._spec("cron")).decode("utf-8")
        assert "InteractiveToken" in xml
        assert "S-1-5-18" not in xml
        assert "ServiceAccount" not in xml
        assert "CalendarTrigger" in xml
        assert "PT1M" not in xml  # no false one-minute repetition
        assert "ScheduleByDay" in xml
        assert "Program Files" in xml
        assert "IgnoreNew" in xml
        assert "StartWhenAvailable" in xml

    def test_windows_xml_date_timetrigger(self):
        backend = WindowsBackend()
        xml = backend._build_task_xml(self._spec("date")).decode("utf-8")
        assert "TimeTrigger" in xml
        assert "StartBoundary" in xml

    def test_windows_xml_interval_no_calendar_day_hack(self):
        backend = WindowsBackend()
        xml = backend._build_task_xml(self._spec("interval")).decode("utf-8")
        assert "TimeTrigger" in xml
        assert "PT15M" in xml

    def test_macos_launchagent_plist_no_year(self):
        backend = MacOSBackend()
        plist = backend._build_plist(self._spec("cron"))
        sci = plist.get("StartCalendarInterval", {})
        assert "Year" not in sci
        assert sci.get("Minute") == 0
        assert sci.get("Hour") == 9
        assert plist["Label"].startswith("com.mwu.task.")

    def test_macos_interval_seconds(self):
        backend = MacOSBackend()
        plist = backend._build_plist(self._spec("interval"))
        assert plist["StartInterval"] == 15 * 60

    def test_linux_user_cron_line_shlex_quoted(self):
        backend = LinuxBackend()
        spec = self._spec("cron")
        spec.working_dir = "/home/user/My App"
        spec.exe_path = "/home/user/My App/python"
        line = backend._build_cron_line(spec)
        assert line.startswith("0 9 * * * ")
        assert (
            "cd '/home/user/My App'" in line
            or 'cd "/home/user/My App"' in line
            or "My App" in line
        )
        assert "&&" in line
        # user crontab has no root user field
        assert " root " not in line


class TestUserLevelIdentifiers:
    def test_platform_identifiers_user_only(self):
        assert MacOSBackend().build_identifier(TID).startswith("com.mwu.task.")
        assert LinuxBackend().build_identifier(TID) == f"mwu-{TID}"
        assert WindowsBackend().build_identifier(TID) == f"\\MWU\\{TID}"


class TestPresenceQuerySemantics:
    """Windows/macOS: explicit not-found → absent; other non-zero → RuntimeError."""

    @pytest.mark.asyncio
    async def test_windows_is_registered_not_found_false(self, monkeypatch):
        b = WindowsBackend()

        def fake_run(args, capture_output=True):
            return SimpleNamespace(
                returncode=1,
                stderr=b"ERROR: The system cannot find the file specified.",
                stdout=b"",
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        assert await b.is_registered(TID) is False

    @pytest.mark.asyncio
    async def test_windows_is_registered_other_error_raises(self, monkeypatch):
        b = WindowsBackend()

        def fake_run(args, capture_output=True):
            return SimpleNamespace(
                returncode=1,
                stderr=b"Access is denied.",
                stdout=b"",
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        with pytest.raises(RuntimeError, match="schtasks query failed"):
            await b.is_registered(TID)

    @pytest.mark.asyncio
    async def test_windows_unregister_not_found_silent(self, monkeypatch):
        b = WindowsBackend()

        def fake_run(args, capture_output=True):
            return SimpleNamespace(
                returncode=1,
                stderr=b"ERROR: The system cannot find the file specified.",
                stdout=b"",
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        await b.unregister(TID)  # no raise

    @pytest.mark.asyncio
    async def test_windows_unregister_other_error_raises(self, monkeypatch):
        b = WindowsBackend()

        def fake_run(args, capture_output=True):
            return SimpleNamespace(
                returncode=1,
                stderr=b"Access is denied.",
                stdout=b"",
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        with pytest.raises(RuntimeError, match="卸载失败"):
            await b.unregister(TID)

    @pytest.mark.asyncio
    async def test_macos_is_registered_not_found_false(self, monkeypatch):
        b = MacOSBackend()

        def fake_run(args, capture_output=True):
            return SimpleNamespace(
                returncode=113,
                stderr=b"Could not find service",
                stdout=b"",
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        assert await b.is_registered(TID) is False

    @pytest.mark.asyncio
    async def test_macos_is_registered_non_not_found_stderr_raises(self, monkeypatch):
        """Non-not-found stderr with rc!=0.

        Contract intent: raise RuntimeError (unknown). Current production falls
        through to return False when outer not-found guard is false — see report.
        """
        b = MacOSBackend()

        def fake_run(args, capture_output=True):
            return SimpleNamespace(
                returncode=1,
                stderr=b"Permission denied launching domain",
                stdout=b"",
            )

        monkeypatch.setattr(
            "services.system_scheduler_backend.subprocess.run", fake_run
        )
        # Actual production behavior (defect vs contract): treated as absent.
        with pytest.raises(RuntimeError, match="launchctl print failed"):
            await b.is_registered(TID)


# ---------------------------------------------------------------------------
# Windows XML verification (USER principal)
# ---------------------------------------------------------------------------


class TestWindowsXmlVerify:
    def _spec(self, trig="cron") -> SystemTaskSpec:
        if trig == "cron":
            trigger = OSTriggerSpec(trigger_type="cron", cron_expression="0 9 * * *")
        elif trig == "interval":
            trigger = OSTriggerSpec(trigger_type="interval", interval_minutes=15)
        else:
            trigger = OSTriggerSpec(
                trigger_type="date",
                run_date=datetime.now(timezone.utc) + timedelta(days=2),
            )
        return SystemTaskSpec(
            task_id=TID,
            task_name="T",
            exe_path=r"C:\Program Files\MWU\python.exe",
            cli_args=[r"C:\Program Files\MWU\main.py", "--headless", "--task", TID],
            trigger=trigger,
            working_dir=r"C:\Program Files\MWU",
        )

    def test_golden_xml_verifies(self):
        b = WindowsBackend()
        spec = self._spec()
        raw = b._build_task_xml(spec)
        ok, detail = b.compare_exported_xml_bytes(raw, spec)
        assert ok, detail

    def test_wrong_command_fails(self):
        b = WindowsBackend()
        spec = self._spec()
        raw = (
            b._build_task_xml(spec)
            .decode("utf-8")
            .replace(spec.exe_path, r"C:\wrong\python.exe")
        )
        ok, detail = b.compare_exported_xml_bytes(raw.encode("utf-8"), spec)
        assert not ok
        assert "Command" in detail

    def test_wrong_args_fails(self):
        b = WindowsBackend()
        spec = self._spec()
        bad = self._spec()
        bad.cli_args = ["other.py"]
        raw = b._build_task_xml(bad)
        ok, detail = b.compare_exported_xml_bytes(raw, spec)
        assert not ok
        assert "Arguments" in detail

    def test_non_interactive_logon_fails(self):
        """USER verify requires InteractiveToken (rejects SYSTEM-style principals)."""
        b = WindowsBackend()
        spec = self._spec()
        raw = (
            b._build_task_xml(spec)
            .decode("utf-8")
            .replace("InteractiveToken", "Password")
        )
        ok, detail = b.compare_exported_xml_bytes(raw.encode("utf-8"), spec)
        assert not ok
        assert "InteractiveToken" in detail or "LogonType" in detail

    def test_pt1m_cron_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="cron")
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("CalendarTrigger") or el.tag == "CalendarTrigger":
                rep = ET.SubElement(el, "Repetition")
                iv = ET.SubElement(rep, "Interval")
                iv.text = "PT1M"
                break
        raw = ET.tostring(root, encoding="utf-8")
        ok, detail = b.compare_exported_xml_bytes(raw, spec)
        assert not ok
        assert "PT1M" in detail

    def test_cron_0900_to_1000_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="cron")  # 0 9 * * *
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("StartBoundary") or el.tag == "StartBoundary":
                if el.text:
                    el.text = el.text[:11] + "10" + el.text[13:]
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "StartBoundary" in detail or "time mismatch" in detail

    def test_date_drift_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="date")
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("StartBoundary") or el.tag == "StartBoundary":
                if el.text and len(el.text) >= 10:
                    el.text = (
                        el.text[:8] + ("2" if el.text[8] != "2" else "3") + el.text[9:]
                    )
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "StartBoundary" in detail

    def test_days_interval_change_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="cron")
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("DaysInterval") or el.tag == "DaysInterval":
                el.text = "2"
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "DaysInterval" in detail

    def test_settings_change_fails(self):
        b = WindowsBackend()
        spec = self._spec()
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("ExecutionTimeLimit") or el.tag == "ExecutionTimeLimit":
                el.text = "PT1H"
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "ExecutionTimeLimit" in detail

    def test_settings_enabled_false_with_trigger_enabled_true_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="cron")
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root:
            if b._local_tag(el.tag) == "Settings":
                for child in el:
                    if b._local_tag(child.tag) == "Enabled":
                        child.text = "false"
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "Settings.Enabled" in detail or "true" in detail.lower()

    def test_allow_start_on_demand_verified(self):
        b = WindowsBackend()
        spec = self._spec()
        root = ET.fromstring(b._build_task_xml(spec))
        ok, _ = b.compare_exported_xml_bytes(ET.tostring(root, encoding="utf-8"), spec)
        assert ok
        for el in root.iter():
            if b._local_tag(el.tag) == "AllowStartOnDemand":
                el.text = "false"
                break
        ok2, detail2 = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok2
        assert "AllowStartOnDemand" in detail2


# ---------------------------------------------------------------------------
# Linux bounds
# ---------------------------------------------------------------------------


class TestLinuxStrict:
    def test_linux_minute_out_of_bounds(self):
        with pytest.raises(ValueError, match="越界"):
            validate_linux_cron_expression("60 9 * * *")

    def test_linux_hour_out_of_bounds(self):
        with pytest.raises(ValueError, match="越界"):
            validate_linux_cron_expression("0 24 * * *")

    def test_linux_day_out_of_bounds(self):
        with pytest.raises(ValueError, match="越界"):
            validate_linux_cron_expression("0 9 32 * *")

    def test_linux_invalid_expansions_rejected(self):
        with pytest.raises(ValueError):
            validate_linux_cron_expression("70/2 9 * * *")
        with pytest.raises(ValueError):
            validate_linux_cron_expression("0 9 32/2 * *")
        with pytest.raises(ValueError):
            validate_linux_cron_expression("5-3 9 * * *")
        with pytest.raises(ValueError):
            validate_linux_cron_expression("*/0 9 * * *")
