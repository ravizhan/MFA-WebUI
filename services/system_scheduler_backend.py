"""
OS 级调度器后端 —— 策略模式实现。
支持 Windows (schtasks)、macOS (launchd)、Linux (user crontab)。

仅用户级原生唤醒；无 SYSTEM/root 提权路径。
cron 翻译消费 services.native_cron 纯函数；无 date/interval 分支。
"""

from __future__ import annotations

import csv
import io
import logging
import os
import platform
import plistlib
import re
import shlex
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from services.native_cron import (
    NativeCron,
    SchtasksSpec,
    to_crontab_line,
    to_launchd_calendar,
    to_schtasks,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_TASK_ID_RE = re.compile(r"^[a-f0-9-]{36}$")
_XML_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_MWU_CRON_MARKER_RE = re.compile(r"#\s*MWU:([a-f0-9-]{36})")

_SCHTASKS_DOW_TO_XML = {
    "SUN": "Sunday",
    "MON": "Monday",
    "TUE": "Tuesday",
    "WED": "Wednesday",
    "THU": "Thursday",
    "FRI": "Friday",
    "SAT": "Saturday",
}
_SCHTASKS_MONTH_TO_XML = {
    "JAN": "January",
    "FEB": "February",
    "MAR": "March",
    "APR": "April",
    "MAY": "May",
    "JUN": "June",
    "JUL": "July",
    "AUG": "August",
    "SEP": "September",
    "OCT": "October",
    "NOV": "November",
    "DEC": "December",
}
_ALL_MONTHS_XML = list(_SCHTASKS_MONTH_TO_XML.values())


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NativeTaskSpec:
    """OS registration payload (no pydantic)."""

    task_id: str
    task_name: str
    exe_path: str
    cli_args: list[str]
    cron: NativeCron
    working_dir: str


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_uid() -> int:
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid else 0


def validate_task_id(task_id: str) -> None:
    if not _TASK_ID_RE.match(task_id):
        raise ValueError(
            f"无效的 task_id 格式: {task_id!r}，必须是标准 UUID 格式（36 位十六进制+连字符）"
        )


def windows_quote_argument(arg: str) -> str:
    """Windows CreateProcess command-line quoting (MSDN rules)."""
    return subprocess.list2cmdline([arg])


def windows_join_args(args: list[str]) -> str:
    """Join argv into a single Windows command-line string (MSDN rules)."""
    return subprocess.list2cmdline(args)


def _run_text(
    args: list[str], *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing stdout/stderr as UTF-8 str."""
    return subprocess.run(
        args,
        capture_output=True,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _parse_hhmm(start_time: str) -> tuple[int, int]:
    hour_s, minute_s = start_time.split(":", 1)
    return int(hour_s), int(minute_s)


def _next_start_boundary(hour: int, minute: int) -> datetime:
    now = datetime.now().astimezone()
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= now:
        start = start + timedelta(days=1)
    return start


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class SystemSchedulerBackend(ABC):
    """OS 级用户唤醒后端抽象。"""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """返回平台标识: 'windows' | 'macos' | 'linux'"""

    @abstractmethod
    def build_identifier(self, task_id: str) -> str:
        """构建 OS 侧任务标识。"""

    @abstractmethod
    def register(self, spec: NativeTaskSpec) -> None:
        """幂等注册：已存在则更新。"""

    @abstractmethod
    def unregister(self, task_id: str) -> None:
        """幂等卸载：不存在则静默成功；非 not-found 错误抛出。"""

    @abstractmethod
    def is_registered(self, task_id: str) -> bool:
        """查询注册状态。明确 not-found → False；其他错误抛 RuntimeError。"""

    @abstractmethod
    def verify_registration(self, spec: NativeTaskSpec) -> tuple[bool, str]:
        """注册后校验。返回 (ok, detail)。"""

    @abstractmethod
    def list_registered_task_ids(self) -> list[str]:
        """列出本机已注册的 MWU 任务 UUID。"""


def _windows_is_not_found(stderr: str) -> bool:
    s = stderr.lower()
    return (
        "ERROR: The system cannot find the file specified" in stderr
        or "does not exist" in s
        or "cannot find the file specified" in s
    )


def _macos_is_not_found(stderr: str) -> bool:
    return (
        "Could not find" in stderr
        or "No such process" in stderr
        or "not found" in stderr.lower()
    )


# ---------------------------------------------------------------------------
# Windows 后端
# ---------------------------------------------------------------------------


class WindowsBackend(SystemSchedulerBackend):
    """Windows Task Scheduler 后端，使用 schtasks /create /xml（用户级）。"""

    platform_name = "windows"

    def build_identifier(self, task_id: str) -> str:
        return f"\\MWU\\{task_id}"

    def register(self, spec: NativeTaskSpec) -> None:
        validate_task_id(spec.task_id)

        xml_bytes = self._build_task_xml(spec)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
                f.write(xml_bytes)
                temp_path = f.name

            task_path = self.build_identifier(spec.task_id)
            self._run_schtasks(
                ["schtasks", "/create", "/xml", temp_path, "/tn", task_path, "/f"],
                check=True,
            )
            logger.info("Windows 任务注册成功: %s", task_path)
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            raise RuntimeError(f"schtasks 注册失败: {stderr.strip() or e}") from e
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        task_path = self.build_identifier(task_id)
        proc = _run_text(["schtasks", "/delete", "/tn", task_path, "/f"])
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            if _windows_is_not_found(stderr):
                return
            raise RuntimeError(f"schtasks 卸载失败: {stderr.strip()}")

    def is_registered(self, task_id: str) -> bool:
        validate_task_id(task_id)
        task_path = self.build_identifier(task_id)
        proc = _run_text(["schtasks", "/query", "/tn", task_path, "/fo", "list"])
        if proc.returncode == 0:
            return True
        stderr = proc.stderr or ""
        if _windows_is_not_found(stderr):
            return False
        raise RuntimeError(
            f"schtasks query failed: {stderr.strip() or proc.returncode}"
        )

    def verify_registration(self, spec: NativeTaskSpec) -> tuple[bool, str]:
        task_path = self.build_identifier(spec.task_id)
        # NOTE: schtasks /query /xml emits UTF-16 LE; keep raw bytes.
        proc = subprocess.run(
            ["schtasks", "/query", "/tn", task_path, "/xml"],
            capture_output=True,
        )
        if proc.returncode != 0:
            stderr = cast(bytes, proc.stderr or b"").decode("utf-8", errors="replace")
            if _windows_is_not_found(stderr):
                return False, "schtasks query/xml not found"
            return False, f"schtasks query/xml failed: {stderr.strip()}"
        raw = cast(bytes, proc.stdout or b"")
        try:
            return self.compare_exported_xml_bytes(raw, spec)
        except Exception as e:
            return False, f"xml verify error: {e}"

    def list_registered_task_ids(self) -> list[str]:
        proc = _run_text(["schtasks", "/query", "/fo", "csv", "/nh"])
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            # Empty task list can still succeed; hard failure otherwise.
            if _windows_is_not_found(stderr):
                return []
            # Some locales return success with empty stdout when no tasks.
            if not (proc.stdout or "").strip() and not stderr:
                return []
            raise RuntimeError(
                f"schtasks query/csv failed: {stderr or proc.returncode}"
            )
        ids: list[str] = []
        for row in csv.reader(io.StringIO(proc.stdout or "")):
            if not row:
                continue
            name = row[0].strip().strip('"')
            if not name.startswith("\\MWU\\"):
                continue
            task_id = name[len("\\MWU\\") :]
            if _TASK_ID_RE.match(task_id):
                ids.append(task_id)
        return ids

    def compare_exported_xml_bytes(
        self, raw: bytes, spec: NativeTaskSpec
    ) -> tuple[bool, str]:
        """Public helper for unit tests (no schtasks required)."""
        return self._compare_exported_xml(raw, spec)

    def _decode_task_xml(self, raw: bytes) -> ET.Element:
        for decoder in (
            lambda b: b.decode("utf-16"),
            lambda b: b.decode("utf-8-sig"),
            lambda b: b.decode("utf-8"),
        ):
            try:
                decoded = decoder(raw)
                if "<Task" in decoded or "<task" in decoded.lower():
                    return ET.fromstring(decoded)
            except Exception:
                continue
        raise ValueError("unable to parse exported task XML")

    @staticmethod
    def _local_tag(tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[-1]
        return tag

    def _find_desc(self, root: ET.Element, name: str) -> ET.Element | None:
        for el in root.iter():
            if self._local_tag(el.tag) == name:
                return el
        return None

    def _find_settings_child(self, root: ET.Element, name: str) -> ET.Element | None:
        for el in root.iter():
            if self._local_tag(el.tag) != "Settings":
                continue
            for child in el:
                if self._local_tag(child.tag) == name:
                    return child
        return None

    def _compare_exported_xml(
        self, raw: bytes, spec: NativeTaskSpec
    ) -> tuple[bool, str]:
        root = self._decode_task_xml(raw)
        logon = self._find_desc(root, "LogonType")
        if logon is None or (logon.text or "") != "InteractiveToken":
            return False, (
                f"USER LogonType expected InteractiveToken, got "
                f"{getattr(logon, 'text', None)}"
            )

        command = self._find_desc(root, "Command")
        arguments = self._find_desc(root, "Arguments")
        working = self._find_desc(root, "WorkingDirectory")
        if command is None or (command.text or "") != spec.exe_path:
            return False, f"Command mismatch: {getattr(command, 'text', None)!r}"
        expected_args = windows_join_args(spec.cli_args)
        if arguments is None or (arguments.text or "") != expected_args:
            return False, (
                f"Arguments mismatch: {getattr(arguments, 'text', None)!r} "
                f"!= {expected_args!r}"
            )
        if working is None or (working.text or "") != spec.working_dir:
            return False, (
                f"WorkingDirectory mismatch: {getattr(working, 'text', None)!r}"
            )

        for name, expect in (
            ("MultipleInstancesPolicy", "IgnoreNew"),
            ("ExecutionTimeLimit", "PT2H"),
        ):
            el = self._find_settings_child(root, name)
            if el is None or (el.text or "") != expect:
                return False, f"Settings.{name} must be {expect}"

        swa = self._find_settings_child(root, "StartWhenAvailable")
        if swa is None or (swa.text or "").lower() != "true":
            return False, "Settings.StartWhenAvailable must be true"

        settings_enabled = self._find_settings_child(root, "Enabled")
        if settings_enabled is None or (settings_enabled.text or "").lower() != "true":
            return False, "Settings.Enabled must be true"

        alw = self._find_settings_child(root, "AllowStartOnDemand")
        if alw is None or (alw.text or "").lower() != "true":
            return False, "Settings.AllowStartOnDemand must be true"

        return self._compare_trigger_xml(root, to_schtasks(spec.cron))

    def _compare_trigger_xml(
        self, root: ET.Element, sch: SchtasksSpec
    ) -> tuple[bool, str]:
        hour, minute = _parse_hhmm(sch.start_time)

        def _start_boundary_ok() -> tuple[bool, str]:
            sb = self._find_desc(root, "StartBoundary")
            if sb is None or not sb.text:
                return False, "StartBoundary missing"
            try:
                dt = datetime.fromisoformat(sb.text)
            except Exception:
                return False, f"StartBoundary unparseable: {sb.text!r}"
            if dt.minute != minute or dt.hour != hour or dt.second != 0:
                return False, (
                    f"StartBoundary time mismatch: "
                    f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} "
                    f"!= {hour:02d}:{minute:02d}:00"
                )
            return True, "ok"

        schedule = sch.schedule.upper()
        if schedule == "HOURLY":
            if self._find_desc(root, "TimeTrigger") is None:
                return False, "expected TimeTrigger for hourly"
            interval_el = self._find_desc(root, "Interval")
            if interval_el is None or (interval_el.text or "") != "PT1H":
                return False, (
                    f"hourly Interval must be PT1H, got "
                    f"{getattr(interval_el, 'text', None)!r}"
                )
            ok, detail = _start_boundary_ok()
            if not ok:
                return False, detail
            return True, "xml verified"

        if self._find_desc(root, "CalendarTrigger") is None:
            return False, f"expected CalendarTrigger for {schedule.lower()}"

        # Reject PT1M-style minute repetition leftovers.
        for el in root.iter():
            if self._local_tag(el.tag) == "Interval" and (el.text or "") == "PT1M":
                return False, "cron must not use PT1M repetition"

        ok, detail = _start_boundary_ok()
        if not ok:
            return False, detail

        if schedule == "DAILY":
            if self._find_desc(root, "ScheduleByDay") is None:
                return False, "daily requires ScheduleByDay"
            days = self._find_desc(root, "DaysInterval")
            if days is None or (days.text or "") != "1":
                return False, (
                    f"daily DaysInterval must be 1, got {getattr(days, 'text', None)!r}"
                )
        elif schedule == "WEEKLY":
            if self._find_desc(root, "ScheduleByWeek") is None:
                return False, "weekly requires ScheduleByWeek"
            expected_day = _SCHTASKS_DOW_TO_XML.get(sch.day_of_week or "")
            if not expected_day:
                return False, f"weekly missing day_of_week: {sch.day_of_week!r}"
            if self._find_desc(root, expected_day) is None:
                return False, f"weekly DaysOfWeek missing {expected_day}"
        elif schedule == "MONTHLY":
            if self._find_desc(root, "ScheduleByMonth") is None:
                return False, "monthly requires ScheduleByMonth"
            day_el = self._find_desc(root, "Day")
            if day_el is None or (day_el.text or "") != str(sch.day_of_month):
                return False, (
                    f"monthly Day mismatch: {getattr(day_el, 'text', None)!r} "
                    f"!= {sch.day_of_month!r}"
                )
            if sch.months:
                month_xml = _SCHTASKS_MONTH_TO_XML.get(sch.months)
                if not month_xml or self._find_desc(root, month_xml) is None:
                    return False, f"monthly Months missing {sch.months}"
        else:
            return False, f"unknown schedule: {schedule}"

        # Trigger Enabled
        en = None
        for el in root.iter():
            if self._local_tag(el.tag) in ("CalendarTrigger", "TimeTrigger"):
                for child in el:
                    if self._local_tag(child.tag) == "Enabled":
                        en = child
                        break
        if en is None or (en.text or "").lower() != "true":
            return False, "trigger Enabled must be true"
        return True, "xml verified"

    @staticmethod
    def _run_schtasks(
        args: list[str], check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return _run_text(args, check=check)

    def _build_task_xml(self, spec: NativeTaskSpec) -> bytes:
        """Build schema-valid user-level Task Scheduler XML."""
        ET.register_namespace("", _XML_NS)
        root = ET.Element(f"{{{_XML_NS}}}Task", version="1.2")

        ri = ET.SubElement(root, "RegistrationInfo")
        desc = ET.SubElement(ri, "Description")
        desc.text = f"MWU Scheduled Task: {spec.task_name}"
        uri = ET.SubElement(ri, "URI")
        uri.text = f"\\MWU\\{spec.task_id}"

        principals = ET.SubElement(root, "Principals")
        principal = ET.SubElement(principals, "Principal")
        principal.set("id", "Author")
        lt = ET.SubElement(principal, "LogonType")
        lt.text = "InteractiveToken"

        triggers = ET.SubElement(root, "Triggers")
        self._add_triggers(triggers, to_schtasks(spec.cron))

        actions = ET.SubElement(root, "Actions")
        actions.set("Context", "Author")
        exec_el = ET.SubElement(actions, "Exec")
        cmd = ET.SubElement(exec_el, "Command")
        cmd.text = spec.exe_path
        args = ET.SubElement(exec_el, "Arguments")
        args.text = windows_join_args(spec.cli_args)
        wd = ET.SubElement(exec_el, "WorkingDirectory")
        wd.text = spec.working_dir

        settings = ET.SubElement(root, "Settings")
        swa = ET.SubElement(settings, "StartWhenAvailable")
        swa.text = "true"
        etl = ET.SubElement(settings, "ExecutionTimeLimit")
        etl.text = "PT2H"
        mip = ET.SubElement(settings, "MultipleInstancesPolicy")
        mip.text = "IgnoreNew"
        enabled = ET.SubElement(settings, "Enabled")
        enabled.text = "true"
        allow_start = ET.SubElement(settings, "AllowStartOnDemand")
        allow_start.text = "true"

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _add_triggers(self, parent: ET.Element, sch: SchtasksSpec) -> None:
        schedule = sch.schedule.upper()
        hour, minute = _parse_hhmm(sch.start_time)

        if schedule == "HOURLY":
            trigger = ET.SubElement(parent, "TimeTrigger")
            sb = ET.SubElement(trigger, "StartBoundary")
            sb.text = _next_start_boundary(hour, minute).isoformat(timespec="seconds")
            enabled = ET.SubElement(trigger, "Enabled")
            enabled.text = "true"
            rep = ET.SubElement(trigger, "Repetition")
            interval = ET.SubElement(rep, "Interval")
            interval.text = "PT1H"
            stop = ET.SubElement(rep, "StopAtDurationEnd")
            stop.text = "false"
            return

        trigger = ET.SubElement(parent, "CalendarTrigger")
        sb = ET.SubElement(trigger, "StartBoundary")
        sb.text = _next_start_boundary(hour, minute).isoformat(timespec="seconds")
        enabled = ET.SubElement(trigger, "Enabled")
        enabled.text = "true"

        if schedule == "DAILY":
            schedule_by_day = ET.SubElement(trigger, "ScheduleByDay")
            days_interval = ET.SubElement(schedule_by_day, "DaysInterval")
            days_interval.text = "1"
            return

        if schedule == "WEEKLY":
            if not sch.day_of_week:
                raise ValueError("weekly 触发器缺少 day_of_week")
            day_xml = _SCHTASKS_DOW_TO_XML.get(sch.day_of_week)
            if not day_xml:
                raise ValueError(f"无效的 day_of_week: {sch.day_of_week!r}")
            schedule_by_week = ET.SubElement(trigger, "ScheduleByWeek")
            weeks_interval = ET.SubElement(schedule_by_week, "WeeksInterval")
            weeks_interval.text = "1"
            days_of_week = ET.SubElement(schedule_by_week, "DaysOfWeek")
            ET.SubElement(days_of_week, day_xml)
            return

        if schedule == "MONTHLY":
            if sch.day_of_month is None:
                raise ValueError("monthly 触发器缺少 day_of_month")
            schedule_by_month = ET.SubElement(trigger, "ScheduleByMonth")
            days_of_month = ET.SubElement(schedule_by_month, "DaysOfMonth")
            day_el = ET.SubElement(days_of_month, "Day")
            day_el.text = str(sch.day_of_month)
            months_el = ET.SubElement(schedule_by_month, "Months")
            if sch.months:
                month_xml = _SCHTASKS_MONTH_TO_XML.get(sch.months)
                if not month_xml:
                    raise ValueError(f"无效的 months: {sch.months!r}")
                ET.SubElement(months_el, month_xml)
            else:
                for month_xml in _ALL_MONTHS_XML:
                    ET.SubElement(months_el, month_xml)
            return

        raise ValueError(f"不支持的 schtasks schedule: {schedule}")


# ---------------------------------------------------------------------------
# macOS 后端
# ---------------------------------------------------------------------------


class MacOSBackend(SystemSchedulerBackend):
    """macOS 14+ launchd 后端（用户 LaunchAgents）。"""

    platform_name = "macos"

    def build_identifier(self, task_id: str) -> str:
        return f"com.mwu.task.{task_id}"

    def _plist_path(self, task_id: str) -> Path:
        label = self.build_identifier(task_id)
        return Path(f"~/Library/LaunchAgents/{label}.plist").expanduser()

    def _domain(self) -> str:
        return f"gui/{_get_uid()}"

    def register(self, spec: NativeTaskSpec) -> None:
        validate_task_id(spec.task_id)
        label = self.build_identifier(spec.task_id)
        plist_path = self._plist_path(spec.task_id)
        plist_data = self._build_plist(spec)

        plist_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_plist(plist_path, plist_data)
        self._bootstrap_idempotent(label, str(plist_path))
        logger.info("macOS launchd 任务注册成功: %s", label)

    def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        label = self.build_identifier(task_id)
        plist_path = self._plist_path(task_id)
        domain = self._domain()
        proc = _run_text(["launchctl", "bootout", f"{domain}/{label}"])
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            if not _macos_is_not_found(stderr):
                raise RuntimeError(f"launchctl bootout failed: {stderr.strip()}")
        if os.path.exists(str(plist_path)):
            try:
                os.unlink(str(plist_path))
            except PermissionError as e:
                raise RuntimeError(f"无法删除 plist: {plist_path}") from e

    def is_registered(self, task_id: str) -> bool:
        validate_task_id(task_id)
        label = self.build_identifier(task_id)
        domain = self._domain()
        proc = _run_text(["launchctl", "print", f"{domain}/{label}"])
        if proc.returncode == 0:
            return True
        stderr = proc.stderr or ""
        if _macos_is_not_found(stderr) or proc.returncode == 113:
            return False
        detail = stderr.strip() or "no stderr"
        raise RuntimeError(f"launchctl print failed (rc={proc.returncode}): {detail}")

    def verify_registration(self, spec: NativeTaskSpec) -> tuple[bool, str]:
        label = self.build_identifier(spec.task_id)
        plist_path = self._plist_path(spec.task_id)
        domain = self._domain()

        if not os.path.exists(str(plist_path)):
            return False, "plist missing"
        try:
            mode = os.stat(str(plist_path))
            perms = mode.st_mode & 0o777
            if perms not in (0o600, 0o400):
                return False, f"plist permissions {oct(perms)} not 0600/0400"
            with open(plist_path, "rb") as f:
                data = plistlib.load(f)
            expected = self._build_plist(spec)
            if data.get("Label") != expected.get("Label"):
                return False, "label mismatch"
            cal = data.get("StartCalendarInterval", {})
            if "Year" in cal:
                return False, "Year key present (unsupported)"
            if cal != expected.get("StartCalendarInterval"):
                return False, "StartCalendarInterval mismatch"
            if data.get("ProgramArguments") != expected.get("ProgramArguments"):
                return False, "ProgramArguments mismatch"
            if data.get("WorkingDirectory") != expected.get("WorkingDirectory"):
                return False, "WorkingDirectory mismatch"
        except Exception as e:
            return False, f"plist compare failed: {e}"

        proc = _run_text(["launchctl", "print", f"{domain}/{label}"])
        if proc.returncode != 0:
            return False, f"launchctl print {domain}/{label} failed"
        return True, f"verified {domain}/{label}"

    def list_registered_task_ids(self) -> list[str]:
        agents = Path("~/Library/LaunchAgents").expanduser()
        if not agents.is_dir():
            return []
        prefix = "com.mwu.task."
        ids: list[str] = []
        for path in agents.glob("com.mwu.task.*.plist"):
            stem = path.stem  # com.mwu.task.<uuid>
            if not stem.startswith(prefix):
                continue
            task_id = stem[len(prefix) :]
            if _TASK_ID_RE.match(task_id):
                ids.append(task_id)
        return ids

    @staticmethod
    def _write_plist(path: Path, data: dict) -> None:
        with open(path, "wb") as f:
            plistlib.dump(data, f)
        os.chmod(path, 0o600)

    def _bootstrap_idempotent(self, label: str, plist_path_str: str) -> None:
        domain = self._domain()
        target = f"{domain}/{label}"

        _run_text(["launchctl", "bootout", target])
        proc = _run_text(["launchctl", "bootstrap", domain, plist_path_str])
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            raise RuntimeError(f"launchctl bootstrap 失败: {stderr.strip()}")

    def _build_plist(self, spec: NativeTaskSpec) -> dict:
        label = self.build_identifier(spec.task_id)
        log_path = os.path.join(
            spec.working_dir, "config", "logs", f"headless_{spec.task_id}.log"
        )
        return {
            "Label": label,
            "ProgramArguments": [spec.exe_path] + list(spec.cli_args),
            "WorkingDirectory": spec.working_dir,
            "RunAtLoad": False,
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
            "StartCalendarInterval": to_launchd_calendar(spec.cron),
        }


# ---------------------------------------------------------------------------
# Linux 后端
# ---------------------------------------------------------------------------


class LinuxBackend(SystemSchedulerBackend):
    """Linux 用户 crontab 后端。"""

    platform_name = "linux"
    _MWU_MARKER_RE = re.compile(r"^#\s*MWU:([a-f0-9-]{36})\s*$")
    _CRONTAB_LOCK_NAME = "mwu-crontab.lock"

    def build_identifier(self, task_id: str) -> str:
        return f"# MWU:{task_id}"

    def register(self, spec: NativeTaskSpec) -> None:
        validate_task_id(spec.task_id)
        lock = self._acquire_crontab_lock()
        try:
            cron_line = self._build_cron_line(spec)
            crontab_text = self._read_crontab()
            lines = crontab_text.splitlines(True)
            new_lines: list[str] = []
            skip_next = False
            for line in lines:
                stripped = line.strip()
                if stripped == f"# MWU:{spec.task_id}":
                    skip_next = True
                    continue
                if skip_next:
                    skip_next = False
                    continue
                new_lines.append(line)
            entry = f"# MWU:{spec.task_id}\n{cron_line}\n"
            new_crontab = "".join(new_lines) + entry
            self._write_crontab(new_crontab)
            logger.info("Linux 任务注册成功: %s", spec.task_id)
        finally:
            lock.release()

    def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        lock = self._acquire_crontab_lock()
        try:
            self._remove_from_user_crontab_unlocked(task_id)
        finally:
            lock.release()

    def is_registered(self, task_id: str) -> bool:
        validate_task_id(task_id)
        lock = self._acquire_crontab_lock()
        try:
            marker = f"# MWU:{task_id}"
            return marker in self._read_crontab()
        finally:
            lock.release()

    def verify_registration(self, spec: NativeTaskSpec) -> tuple[bool, str]:
        expected_line = self._build_cron_line(spec)
        marker = f"# MWU:{spec.task_id}"
        lock = self._acquire_crontab_lock()
        try:
            text = self._read_crontab()
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.strip() == marker:
                    if i + 1 < len(lines) and lines[i + 1].strip() == expected_line:
                        return True, "user crontab marker+line match"
                    return False, "user crontab line mismatch"
            return False, "user crontab marker missing"
        finally:
            lock.release()

    def list_registered_task_ids(self) -> list[str]:
        lock = self._acquire_crontab_lock()
        try:
            text = self._read_crontab()
            return _MWU_CRON_MARKER_RE.findall(text)
        finally:
            lock.release()

    def _crontab_lock_path(self) -> Path:
        return Path.home() / ".mwu" / self._CRONTAB_LOCK_NAME

    def _acquire_crontab_lock(self):
        from services.process_lock import AdvisoryFileLock

        lock = AdvisoryFileLock(self._crontab_lock_path())
        lock.acquire(timeout_seconds=30.0)
        return lock

    def _read_crontab(self) -> str:
        proc = _run_text(["crontab", "-l"])
        if proc.returncode != 0:
            err = f"{proc.stderr or ''}{proc.stdout or ''}"
            err_l = err.lower()
            if "no crontab for" in err_l or "no crontab" in err_l:
                return ""
            raise RuntimeError(f"crontab -l failed: {err.strip() or proc.returncode}")
        return proc.stdout or ""

    def _write_crontab(self, content: str) -> None:
        proc = subprocess.run(
            ["crontab", "-"],
            input=content,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            raise RuntimeError(f"crontab 写入失败: {stderr.strip()}")

    def _remove_from_user_crontab_unlocked(self, task_id: str) -> None:
        crontab_text = self._read_crontab()
        if not crontab_text:
            return
        lines = crontab_text.splitlines(True)
        new_lines: list[str] = []
        skip_next = False
        for line in lines:
            stripped = line.strip()
            if self._MWU_MARKER_RE.match(stripped):
                m = self._MWU_MARKER_RE.match(stripped)
                if m and m.group(1) == task_id:
                    skip_next = True
                    continue
            if skip_next:
                skip_next = False
                continue
            new_lines.append(line)

        new_crontab = "".join(new_lines)
        if not new_crontab.strip():
            proc = _run_text(["crontab", "-r"])
            if proc.returncode != 0:
                stderr = proc.stderr or ""
                if "no crontab for" not in stderr.lower():
                    raise RuntimeError(f"crontab -r failed: {stderr.strip()}")
        else:
            self._write_crontab(new_crontab)

    def _build_command_body(self, spec: NativeTaskSpec) -> str:
        wd = shlex.quote(spec.working_dir)
        exe = shlex.quote(spec.exe_path)
        args = " ".join(shlex.quote(a) for a in spec.cli_args)
        return f"cd {wd} && {exe} {args}".rstrip()

    def _build_cron_line(self, spec: NativeTaskSpec) -> str:
        return f"{to_crontab_line(spec.cron)} {self._build_command_body(spec)}"


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def get_backend(platform_name: str | None = None) -> SystemSchedulerBackend:
    """根据当前平台返回对应后端实例。"""
    system = (platform_name or platform.system()).lower()
    if system in ("windows", "win32"):
        return WindowsBackend()
    if system in ("darwin", "macos"):
        return MacOSBackend()
    if system == "linux":
        return LinuxBackend()
    raise RuntimeError(f"不支持的平台: {system}")


def build_native_command(
    app_root: Path, task_id: str, *, frozen: bool | None = None
) -> tuple[str, list[str]]:
    """Build source/frozen native command for OS registration.

    Source mode: python_executable + absolute main.py + --scheduled-task id
    Frozen mode: executable + --scheduled-task id
    """
    import sys

    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen

    if is_frozen:
        return sys.executable, ["--scheduled-task", task_id]
    main_py = str((Path(app_root) / "main.py").resolve())
    return sys.executable, [main_py, "--scheduled-task", task_id]
