"""
OS 级调度器后端 —— 策略模式实现。
支持 Windows (schtasks)、macOS (launchd)、Linux (user crontab)。

仅用户级原生唤醒；无 SYSTEM/root 提权路径，无 scope 参数。

Normative trigger contract (no silent approximation):
  Windows date: future timezone-aware TimeTrigger only
  Windows interval: whole minutes 1..44640, no start/end modifiers
  Windows cron: numeric fixed daily M H * * * only
  macOS date: rejected
  macOS interval: positive StartInterval, no start/end; sleep/overlap warning
  macOS cron: numeric fixed daily M H * * * only
  Linux date/interval: rejected
  Linux cron: numeric five-field with DOW *; names/extensions/restricted DOW rejected
"""

from __future__ import annotations

import asyncio
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
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from apscheduler.triggers.cron import CronTrigger

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    OSTriggerSpec,
    SystemTaskSpec,
    TriggerConfig,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_TASK_ID_RE = re.compile(r"^[a-f0-9-]{36}$")
_XML_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
# Numeric fixed daily: M H * * *
_FIXED_DAILY_CRON_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$")
_MAX_INTERVAL_MINUTES = 44640  # 31 days


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


def parse_fixed_daily_cron(expr: str) -> tuple[int, int]:
    """Parse numeric fixed daily M H * * *. Returns (minute, hour)."""
    m = _FIXED_DAILY_CRON_RE.match(expr.strip())
    if not m:
        raise ValueError(f"仅支持数值固定每日 cron 'M H * * *'，收到: {expr!r}")
    minute = int(m.group(1))
    hour = int(m.group(2))
    if not (0 <= minute <= 59):
        raise ValueError(f"cron 分钟越界: {minute}")
    if not (0 <= hour <= 23):
        raise ValueError(f"cron 小时越界: {hour}")
    return minute, hour


def validate_linux_cron_expression(expr: str) -> str:
    """Validate Linux cron: numeric five-field with bounds; DOW must be *.

    Delegates syntax/bounds/range/step/descending-range/zero-step validation
    to APScheduler's ``CronTrigger.from_crontab`` (already a project dep),
    layered with MWU's strict policy: numeric-only tokens (no ``MON``/``JAN``/``L``/
    ``W``/``#``/``@``) and day-of-week must be ``*`` (DOM+DOW restricted translation
    has no safe APScheduler→cron mapping and is rejected pre-emptively).
    """
    expr = expr.strip()
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"无效的 cron 表达式（需要 5 个字段）: {expr!r}")
    field_names = ("minute", "hour", "day", "month", "weekday")
    for name, value in zip(field_names, fields):
        if re.search(r"[A-Za-z@]", value):
            raise ValueError(f"Linux cron 拒绝名称/扩展字段 {name}={value!r}")
    if fields[4] != "*":
        raise ValueError(
            "Linux cron 暂不支持受限 day-of-week（需 DOW=*）；"
            "DOM+DOW 同时限制在 APScheduler→cron 星期翻译验证前被拒绝"
        )
    try:
        CronTrigger.from_crontab(expr)
    except ValueError as e:
        raise ValueError(f"Linux cron 越界或语法错误: {e}") from e
    return expr


def windows_quote_argument(arg: str) -> str:
    """Windows CreateProcess command-line quoting (MSDN rules).

    Delegates to ``subprocess.list2cmdline``, which implements the same
    backslash-doubling + space/tab/quote-driven quoting rules used by
    CreateProcess on Windows (CPython's own implementation of list2cmdline is
    the canonical reference for the rules documented at
    https://learn.microsoft.com/windows/win32/api/processthreadapi/nf-processthreadapi-createprocessw).
    """
    return subprocess.list2cmdline([arg])


def windows_join_args(args: list[str]) -> str:
    """Join argv into a single Windows command-line string (MSDN rules).

    Equivalent to ``subprocess.list2cmdline(args)``; kept as a named helper
    for site readability and to mirror the symmetric single-arg form above.
    """
    return subprocess.list2cmdline(args)


def _run_text(
    args: list[str], *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing stdout/stderr as UTF-8 str.

    Standardizes encoding (utf-8) and error handling (errors=replace) so every
    caller can treat ``proc.stderr`` / ``proc.stdout`` directly as ``str``.
    Use :func:`subprocess.run` directly with ``capture_output=True`` (no
    ``text=``) when raw bytes are required (e.g. Windows Task Scheduler XML
    which may be UTF-16 encoded).
    """
    return subprocess.run(
        args,
        capture_output=True,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def ensure_timezone_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Local timezone attachment for Windows StartBoundary
        local = datetime.now().astimezone().tzinfo
        return dt.replace(tzinfo=local)
    return dt


def interval_total_minutes_strict(config: IntervalTriggerConfig) -> int:
    """Whole-minute intervals only; reject seconds and start/end modifiers."""
    if config.seconds and config.seconds != 0:
        raise ValueError("interval 不支持秒级精度；仅接受整分钟 1..44640")
    if config.start_date is not None or config.end_date is not None:
        raise ValueError("interval 不支持 start_date/end_date 修饰符")
    weeks = config.weeks or 0
    days = config.days or 0
    hours = config.hours or 0
    minutes = config.minutes or 0
    total = weeks * 7 * 24 * 60 + days * 24 * 60 + hours * 60 + minutes
    if total < 1 or total > _MAX_INTERVAL_MINUTES:
        raise ValueError(
            f"interval 必须为整分钟 1..{_MAX_INTERVAL_MINUTES}，收到 {total}"
        )
    return total


# ---------------------------------------------------------------------------
# Trigger 映射（platform-agnostic raw mapping + validation helpers）
# ---------------------------------------------------------------------------


def map_trigger_to_os_spec(trigger_config: TriggerConfig) -> OSTriggerSpec:
    """Map APScheduler trigger to OSTriggerSpec with strict semantics.

    Note: platform-specific acceptance is enforced by validate_trigger_for_platform.
    """
    if isinstance(trigger_config, CronTriggerConfig):
        return OSTriggerSpec(
            trigger_type="cron",
            cron_expression=trigger_config.cron.strip(),
        )
    if isinstance(trigger_config, DateTriggerConfig):
        run_date = ensure_timezone_aware(trigger_config.run_date)
        now = datetime.now(run_date.tzinfo)
        if run_date <= now:
            raise ValueError("DateTrigger 已过期，无法注册")
        return OSTriggerSpec(trigger_type="date", run_date=run_date)
    if isinstance(trigger_config, IntervalTriggerConfig):
        total = interval_total_minutes_strict(trigger_config)
        return OSTriggerSpec(trigger_type="interval", interval_minutes=total)
    raise TypeError(f"未知的触发器类型: {type(trigger_config)}")


def validate_trigger_for_platform(
    platform_name: str, trigger: OSTriggerSpec
) -> list[str]:
    """Validate trigger against normative platform matrix. Returns warnings.

    Raises ValueError on rejection (normalized failure).
    """
    warnings: list[str] = []
    t = trigger.trigger_type

    if platform_name == "windows":
        if t == "date":
            if trigger.run_date is None:
                raise ValueError("Windows date 需要 run_date")
            if trigger.run_date.tzinfo is None:
                raise ValueError("Windows date 需要 timezone-aware run_date")
            if trigger.run_date <= datetime.now(trigger.run_date.tzinfo):
                raise ValueError("Windows date 必须是未来时间")
            return warnings
        if t == "interval":
            mins = trigger.interval_minutes
            if mins is None or mins < 1 or mins > _MAX_INTERVAL_MINUTES:
                raise ValueError(
                    f"Windows interval 仅支持整分钟 1..{_MAX_INTERVAL_MINUTES}"
                )
            return warnings
        if t == "cron":
            if not trigger.cron_expression:
                raise ValueError("cron 缺少表达式")
            parse_fixed_daily_cron(trigger.cron_expression)
            return warnings
        raise ValueError(f"Windows 不支持触发器类型: {t}")

    if platform_name == "macos":
        if t == "date":
            raise ValueError("macOS launchd 拒绝 date 触发器（无安全 Year 语义）")
        if t == "interval":
            mins = trigger.interval_minutes
            if mins is None or mins < 1:
                raise ValueError("macOS interval 需要正整分钟")
            warnings.append("macOS StartInterval 在睡眠期间或作业仍在运行时可能漏触发")
            return warnings
        if t == "cron":
            if not trigger.cron_expression:
                raise ValueError("cron 缺少表达式")
            parse_fixed_daily_cron(trigger.cron_expression)
            return warnings
        raise ValueError(f"macOS 不支持触发器类型: {t}")

    if platform_name == "linux":
        if t == "date":
            raise ValueError("Linux cron 拒绝 date 触发器")
        if t == "interval":
            raise ValueError("Linux cron 拒绝 interval（字段 step 不能表示任意时长）")
        if t == "cron":
            if not trigger.cron_expression:
                raise ValueError("cron 缺少表达式")
            validate_linux_cron_expression(trigger.cron_expression)
            return warnings
        raise ValueError(f"Linux 不支持触发器类型: {t}")

    raise ValueError(f"未知平台: {platform_name}")



# ---------------------------------------------------------------------------
# 抽象基类 —— 六个核心成员（无 scope）
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
    async def register(self, spec: SystemTaskSpec) -> None:
        """幂等注册：已存在则更新。"""

    @abstractmethod
    async def unregister(self, task_id: str) -> None:
        """幂等卸载：不存在则静默成功；非 not-found 错误抛出。"""

    @abstractmethod
    async def is_registered(self, task_id: str) -> bool:
        """查询注册状态。明确 not-found → False；其他错误抛 RuntimeError。"""

    @abstractmethod
    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        """注册后校验。返回 (ok, detail)。"""


def _windows_is_not_found(stderr: str) -> bool:
    s = stderr.lower()
    return (
        "ERROR: The system cannot find the file specified" in stderr
        or "does not exist" in s
        or "cannot find the file specified" in s
    )


def _macos_is_not_found(stderr: str) -> bool:
    return "Could not find" in stderr or "No such process" in stderr or "not found" in stderr.lower()


# ---------------------------------------------------------------------------
# Windows 后端
# ---------------------------------------------------------------------------


class WindowsBackend(SystemSchedulerBackend):
    """Windows Task Scheduler 后端，使用 schtasks /create /xml（用户级）。"""

    platform_name = "windows"

    def build_identifier(self, task_id: str) -> str:
        return f"\\MWU\\{task_id}"

    async def register(self, spec: SystemTaskSpec) -> None:
        validate_task_id(spec.task_id)
        validate_trigger_for_platform(self.platform_name, spec.trigger)

        xml_bytes = self._build_task_xml(spec)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
                f.write(xml_bytes)
                temp_path = f.name

            task_path = self.build_identifier(spec.task_id)
            await asyncio.to_thread(
                self._run_schtasks,
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

    async def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        task_path = self.build_identifier(task_id)
        proc = await asyncio.to_thread(
            _run_text,
            ["schtasks", "/delete", "/tn", task_path, "/f"],
        )
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            if _windows_is_not_found(stderr):
                return
            raise RuntimeError(f"schtasks 卸载失败: {stderr.strip()}")

    async def is_registered(self, task_id: str) -> bool:
        validate_task_id(task_id)
        task_path = self.build_identifier(task_id)
        proc = await asyncio.to_thread(
            _run_text,
            ["schtasks", "/query", "/tn", task_path, "/fo", "list"],
        )
        if proc.returncode == 0:
            return True
        stderr = proc.stderr or ""
        if _windows_is_not_found(stderr):
            return False
        raise RuntimeError(f"schtasks query failed: {stderr.strip() or proc.returncode}")

    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        task_path = self.build_identifier(spec.task_id)
        # NOTE: schtasks /query /xml emits UTF-16 LE; must keep raw bytes for
        # _decode_task_xml's multi-codepage cascade. Do not switch to _run_text.
        proc = await asyncio.to_thread(
            subprocess.run,
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

    def compare_exported_xml_bytes(
        self, raw: bytes, spec: SystemTaskSpec
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
        self, raw: bytes, spec: SystemTaskSpec
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

        expected_root = self._decode_task_xml(self._build_task_xml(spec))
        trig = spec.trigger

        def _sb(el_root: ET.Element) -> str | None:
            sb = self._find_desc(el_root, "StartBoundary")
            return sb.text if sb is not None else None

        if trig.trigger_type == "date":
            if self._find_desc(root, "TimeTrigger") is None:
                return False, "expected TimeTrigger for date"
            if self._find_desc(root, "Repetition") is not None:
                return False, "date trigger must not have Repetition"
            exp_sb, got_sb = _sb(expected_root), _sb(root)
            if exp_sb is None or got_sb is None:
                return False, "date StartBoundary missing"
            if got_sb[:19] != exp_sb[:19]:
                return False, f"date StartBoundary mismatch: {got_sb!r} != {exp_sb!r}"
        elif trig.trigger_type == "interval":
            if self._find_desc(root, "TimeTrigger") is None:
                return False, "expected TimeTrigger for interval"
            interval_el = self._find_desc(root, "Interval")
            mins = trig.interval_minutes or 0
            if mins % (24 * 60) == 0 and mins >= 24 * 60:
                expect = f"P{mins // (24 * 60)}D"
            elif mins % 60 == 0:
                expect = f"PT{mins // 60}H"
            else:
                expect = f"PT{mins}M"
            if interval_el is None or (interval_el.text or "") != expect:
                return False, (
                    f"interval duration mismatch: "
                    f"{getattr(interval_el, 'text', None)!r} != {expect!r}"
                )
            stop = self._find_desc(root, "StopAtDurationEnd")
            if stop is None or (stop.text or "").lower() != "false":
                return False, "interval StopAtDurationEnd must be false"
        elif trig.trigger_type == "cron":
            if self._find_desc(root, "CalendarTrigger") is None:
                return False, "expected CalendarTrigger for cron"
            for el in root.iter():
                if self._local_tag(el.tag) == "Interval" and (el.text or "") == "PT1M":
                    return False, "cron must not use PT1M repetition"
            days = self._find_desc(root, "DaysInterval")
            if days is None or (days.text or "") != "1":
                return False, (
                    f"cron DaysInterval must be 1, got {getattr(days, 'text', None)!r}"
                )
            if self._find_desc(root, "ScheduleByDay") is None:
                return False, "cron fixed daily requires ScheduleByDay"
            minute, hour = parse_fixed_daily_cron(trig.cron_expression or "")
            got_sb = _sb(root)
            if got_sb is None:
                return False, "cron StartBoundary missing"
            try:
                dt = datetime.fromisoformat(got_sb)
            except Exception:
                return False, f"cron StartBoundary unparseable: {got_sb!r}"
            if dt.minute != minute or dt.hour != hour or dt.second != 0:
                return False, (
                    f"cron StartBoundary time mismatch: "
                    f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} "
                    f"!= {hour:02d}:{minute:02d}:00"
                )
            en = None
            for el in root.iter():
                if self._local_tag(el.tag) == "CalendarTrigger":
                    for child in el:
                        if self._local_tag(child.tag) == "Enabled":
                            en = child
                            break
            if en is None or (en.text or "").lower() != "true":
                return False, "cron trigger Enabled must be true"
        return True, "xml verified"

    @staticmethod
    def _run_schtasks(
        args: list[str], check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return _run_text(args, check=check)

    def _build_task_xml(self, spec: SystemTaskSpec) -> bytes:
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
        self._add_triggers(triggers, spec.trigger)

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

    def _add_triggers(self, parent: ET.Element, trigger_spec: OSTriggerSpec) -> None:
        if trigger_spec.trigger_type == "date":
            trigger = ET.SubElement(parent, "TimeTrigger")
            sb = ET.SubElement(trigger, "StartBoundary")
            if trigger_spec.run_date is None:
                raise ValueError("date 类型的触发器缺少 run_date")
            run_date = ensure_timezone_aware(trigger_spec.run_date)
            sb.text = run_date.isoformat(timespec="seconds")
            enabled = ET.SubElement(trigger, "Enabled")
            enabled.text = "true"
            return

        if trigger_spec.trigger_type == "interval":
            mins = trigger_spec.interval_minutes or 0
            if mins < 1 or mins > _MAX_INTERVAL_MINUTES:
                raise ValueError("invalid interval minutes")
            trigger = ET.SubElement(parent, "TimeTrigger")
            sb = ET.SubElement(trigger, "StartBoundary")
            sb.text = datetime.now().astimezone().isoformat(timespec="seconds")
            enabled = ET.SubElement(trigger, "Enabled")
            enabled.text = "true"
            rep = ET.SubElement(trigger, "Repetition")
            interval = ET.SubElement(rep, "Interval")
            if mins % (24 * 60) == 0 and mins >= 24 * 60:
                days = mins // (24 * 60)
                interval.text = f"P{days}D"
            elif mins % 60 == 0:
                hours = mins // 60
                interval.text = f"PT{hours}H"
            else:
                interval.text = f"PT{mins}M"
            stop = ET.SubElement(rep, "StopAtDurationEnd")
            stop.text = "false"
            return

        if not trigger_spec.cron_expression:
            raise ValueError("cron 类型的触发器缺少 cron_expression")
        minute, hour = parse_fixed_daily_cron(trigger_spec.cron_expression)

        trigger = ET.SubElement(parent, "CalendarTrigger")
        now = datetime.now().astimezone()
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= now:
            start = start + timedelta(days=1)
        sb = ET.SubElement(trigger, "StartBoundary")
        sb.text = start.isoformat(timespec="seconds")
        enabled = ET.SubElement(trigger, "Enabled")
        enabled.text = "true"
        schedule_by_day = ET.SubElement(trigger, "ScheduleByDay")
        days_interval = ET.SubElement(schedule_by_day, "DaysInterval")
        days_interval.text = "1"


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

    async def register(self, spec: SystemTaskSpec) -> None:
        validate_task_id(spec.task_id)
        validate_trigger_for_platform(self.platform_name, spec.trigger)
        label = self.build_identifier(spec.task_id)
        plist_path = self._plist_path(spec.task_id)
        plist_data = self._build_plist(spec)

        plist_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._write_plist, plist_path, plist_data)
        await self._bootstrap_idempotent(label, str(plist_path))
        logger.info("macOS launchd 任务注册成功: %s", label)

    async def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        label = self.build_identifier(task_id)
        plist_path = self._plist_path(task_id)
        domain = self._domain()
        proc = await asyncio.to_thread(
            _run_text,
            ["launchctl", "bootout", f"{domain}/{label}"],
        )
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            if not _macos_is_not_found(stderr):
                raise RuntimeError(f"launchctl bootout failed: {stderr.strip()}")
        if await asyncio.to_thread(os.path.exists, str(plist_path)):
            try:
                await asyncio.to_thread(os.unlink, str(plist_path))
            except PermissionError as e:
                raise RuntimeError(f"无法删除 plist: {plist_path}") from e

    async def is_registered(self, task_id: str) -> bool:
        validate_task_id(task_id)
        label = self.build_identifier(task_id)
        domain = self._domain()
        proc = await asyncio.to_thread(
            _run_text,
            ["launchctl", "print", f"{domain}/{label}"],
        )
        if proc.returncode == 0:
            return True
        stderr = proc.stderr or ""
        if _macos_is_not_found(stderr) or proc.returncode == 113:
            return False
        detail = stderr.strip() or "no stderr"
        raise RuntimeError(
            f"launchctl print failed (rc={proc.returncode}): {detail}"
        )

    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        label = self.build_identifier(spec.task_id)
        plist_path = self._plist_path(spec.task_id)
        domain = self._domain()

        if not await asyncio.to_thread(os.path.exists, str(plist_path)):
            return False, "plist missing"
        try:
            mode = await asyncio.to_thread(os.stat, str(plist_path))
            perms = mode.st_mode & 0o777
            if perms not in (0o600, 0o400):
                return False, f"plist permissions {oct(perms)} not 0600/0400"
            with open(plist_path, "rb") as f:
                data = plistlib.load(f)
            expected = self._build_plist(spec)
            if data.get("Label") != expected.get("Label"):
                return False, "label mismatch"
            if "Year" in data.get("StartCalendarInterval", {}):
                return False, "Year key present (unsupported)"
            if data.get("ProgramArguments") != expected.get("ProgramArguments"):
                return False, "ProgramArguments mismatch"
        except Exception as e:
            return False, f"plist compare failed: {e}"

        proc = await asyncio.to_thread(
            _run_text,
            ["launchctl", "print", f"{domain}/{label}"],
        )
        if proc.returncode != 0:
            return False, f"launchctl print {domain}/{label} failed"
        return True, f"verified {domain}/{label}"

    @staticmethod
    def _write_plist(path: Path, data: dict) -> None:
        with open(path, "wb") as f:
            plistlib.dump(data, f)
        os.chmod(path, 0o600)

    async def _bootstrap_idempotent(self, label: str, plist_path_str: str) -> None:
        domain = self._domain()
        target = f"{domain}/{label}"

        await asyncio.to_thread(
            _run_text,
            ["launchctl", "bootout", target],
        )
        proc = await asyncio.to_thread(
            _run_text,
            ["launchctl", "bootstrap", domain, plist_path_str],
        )
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            raise RuntimeError(f"launchctl bootstrap 失败: {stderr.strip()}")

    def _build_plist(self, spec: SystemTaskSpec) -> dict:
        label = self.build_identifier(spec.task_id)
        plist: dict = {
            "Label": label,
            "ProgramArguments": [spec.exe_path] + list(spec.cli_args),
            "WorkingDirectory": spec.working_dir,
            "RunAtLoad": False,
        }
        log_path = os.path.join(
            spec.working_dir, "config", "logs", f"headless_{spec.task_id}.log"
        )
        plist["StandardOutPath"] = log_path
        plist["StandardErrorPath"] = log_path

        trigger_spec = spec.trigger
        if trigger_spec.trigger_type == "cron":
            if not trigger_spec.cron_expression:
                raise ValueError("cron 类型的触发器缺少 cron_expression")
            minute, hour = parse_fixed_daily_cron(trigger_spec.cron_expression)
            plist["StartCalendarInterval"] = {
                "Minute": minute,
                "Hour": hour,
            }
        elif trigger_spec.trigger_type == "date":
            raise ValueError("macOS 拒绝 date 触发器")
        elif trigger_spec.trigger_type == "interval":
            mins = trigger_spec.interval_minutes or 0
            if mins < 1:
                raise ValueError("interval 必须为正")
            plist["StartInterval"] = mins * 60
        return plist


# ---------------------------------------------------------------------------
# Linux 后端
# ---------------------------------------------------------------------------


class LinuxBackend(SystemSchedulerBackend):
    """Linux 用户 crontab 后端。"""

    platform_name = "linux"
    _MWU_MARKER_RE = re.compile(r"^#\s*MWU:([a-f0-9-]{36})\s*$")
    _CRONTAB_LOCK_NAME = "mwu-crontab.lock"

    def build_identifier(self, task_id: str) -> str:
        return f"mwu-{task_id}"

    async def register(self, spec: SystemTaskSpec) -> None:
        validate_task_id(spec.task_id)
        validate_trigger_for_platform(self.platform_name, spec.trigger)
        await self._register_user_cron(spec)
        logger.info("Linux 任务注册成功: %s", spec.task_id)

    async def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        await self._remove_from_user_crontab(task_id)

    async def is_registered(self, task_id: str) -> bool:
        validate_task_id(task_id)
        marker = f"# MWU:{task_id}"
        crontab_text = await self._read_crontab()
        return marker in crontab_text

    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        expected_line = self._build_cron_line(spec)
        marker = f"# MWU:{spec.task_id}"
        text = await self._read_crontab()
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == marker:
                if i + 1 < len(lines) and lines[i + 1].strip() == expected_line:
                    return True, "user crontab marker+line match"
                return False, "user crontab line mismatch"
        return False, "user crontab marker missing"

    def _crontab_lock_path(self) -> Path:
        return Path.home() / ".mwu" / self._CRONTAB_LOCK_NAME

    def _acquire_crontab_lock(self):
        from services.process_lock import AdvisoryFileLock

        lock = AdvisoryFileLock(self._crontab_lock_path())
        lock.acquire(timeout_seconds=30.0)
        return lock

    async def _read_crontab(self) -> str:
        proc = await asyncio.to_thread(_run_text, ["crontab", "-l"])
        if proc.returncode != 0:
            err = f"{proc.stderr or ''}{proc.stdout or ''}"
            err_l = err.lower()
            if "no crontab for" in err_l or "no crontab" in err_l:
                return ""
            raise RuntimeError(f"crontab -l failed: {err.strip() or proc.returncode}")
        return proc.stdout or ""

    async def _write_crontab(self, content: str) -> None:
        proc = await asyncio.to_thread(
            subprocess.run,
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

    async def _remove_from_user_crontab(self, task_id: str) -> None:
        lock = self._acquire_crontab_lock()
        try:
            await self._remove_from_user_crontab_unlocked(task_id)
        finally:
            lock.release()

    async def _remove_from_user_crontab_unlocked(self, task_id: str) -> None:
        crontab_text = await self._read_crontab()
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
            proc = await asyncio.to_thread(_run_text, ["crontab", "-r"])
            if proc.returncode != 0:
                stderr = proc.stderr or ""
                if "no crontab for" not in stderr.lower():
                    raise RuntimeError(f"crontab -r failed: {stderr.strip()}")
        else:
            await self._write_crontab(new_crontab)

    async def _register_user_cron(self, spec: SystemTaskSpec) -> None:
        lock = self._acquire_crontab_lock()
        try:
            cron_line = self._build_cron_line(spec)
            crontab_text = await self._read_crontab()
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
            await self._write_crontab(new_crontab)
        finally:
            lock.release()

    def _build_command_body(self, spec: SystemTaskSpec) -> str:
        wd = shlex.quote(spec.working_dir)
        exe = shlex.quote(spec.exe_path)
        args = " ".join(shlex.quote(a) for a in spec.cli_args)
        return f"cd {wd} && {exe} {args}".rstrip()

    def _build_cron_line(self, spec: SystemTaskSpec) -> str:
        trigger_spec = spec.trigger
        if trigger_spec.trigger_type != "cron" or not trigger_spec.cron_expression:
            raise ValueError("Linux 仅支持 cron 触发器")
        cron_timing = validate_linux_cron_expression(trigger_spec.cron_expression)
        return f"{cron_timing} {self._build_command_body(spec)}"


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

    Source mode: python_executable + absolute main.py + --headless --task id
    Frozen mode: executable + --headless --task id
    """
    import sys

    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen

    if is_frozen:
        return sys.executable, ["--headless", "--task", task_id]
    main_py = str((Path(app_root) / "main.py").resolve())
    return sys.executable, [main_py, "--headless", "--task", task_id]
