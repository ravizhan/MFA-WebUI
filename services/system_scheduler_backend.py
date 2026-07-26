"""
OS 级调度后端（策略模式）：Windows Task Scheduler / macOS launchd / Linux crontab。
"""

from __future__ import annotations

import logging
import os
import platform
import plistlib
import re
import shlex
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from services.native_cron import (
    NativeCron,
    SchtasksSpec,
    to_crontab_line,
    to_launchd_calendar,
    to_schtasks,
)

logger = logging.getLogger(__name__)

_TASK_ID_RE = re.compile(r"^[a-f0-9-]{36}$")
_MWU_CRON_MARKER_RE = re.compile(r"#\s*MWU:([a-f0-9-]{36})")

# Task Scheduler 2.0 COM 常量
_TASK_ACTION_EXEC = 0
_TASK_TRIGGER_TIME = 1
_TASK_TRIGGER_DAILY = 2
_TASK_TRIGGER_WEEKLY = 3
_TASK_TRIGGER_MONTHLY = 4
_TASK_CREATE_OR_UPDATE = 6
_TASK_LOGON_INTERACTIVE_TOKEN = 3
_TASK_INSTANCES_PARALLEL = 0

_SCHTASKS_DOW_TO_COM: dict[str, int] = {
    "SUN": 0x01,
    "MON": 0x02,
    "TUE": 0x04,
    "WED": 0x08,
    "THU": 0x10,
    "FRI": 0x20,
    "SAT": 0x40,
}
_SCHTASKS_MONTH_TO_COM: dict[str, int] = {
    "JAN": 0x001,
    "FEB": 0x002,
    "MAR": 0x004,
    "APR": 0x008,
    "MAY": 0x010,
    "JUN": 0x020,
    "JUL": 0x040,
    "AUG": 0x080,
    "SEP": 0x100,
    "OCT": 0x200,
    "NOV": 0x400,
    "DEC": 0x800,
}
_ALL_MONTHS_COM = 0xFFF


@dataclass(frozen=True)
class NativeTaskSpec:
    """OS 注册载荷（非 pydantic）。"""

    task_id: str
    task_name: str
    exe_path: str
    cli_args: list[str]
    cron: NativeCron
    working_dir: str


def _get_uid() -> int:
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid else 0


def validate_task_id(task_id: str) -> None:
    if not _TASK_ID_RE.match(task_id):
        raise ValueError(
            f"无效的 task_id 格式: {task_id!r}，必须是标准 UUID 格式（36 位十六进制+连字符）"
        )


def windows_quote_argument(arg: str) -> str:
    """按 MSDN 规则对单个 Windows 命令行参数加引号。"""
    return subprocess.list2cmdline([arg])


def windows_join_args(args: list[str]) -> str:
    """按 MSDN 规则将 argv 拼成 Windows 命令行字符串。"""
    return subprocess.list2cmdline(args)


def _run_text(
    args: list[str], *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """以 UTF-8 文本捕获 stdout/stderr 执行子进程。"""
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
    """下一本地日历时刻 hour:minute（日/周/月触发用）。

    返回值必须是 naive 本地墙钟：带 UTC 偏移的 isoformat() 会被
    Task Scheduler 2.0 当作 StartBoundary 的“跨时区同步”语义
    （钉死于绝对瞬时），DST 每次切换都会把日/周/月触发漂移 1 小时。
    """
    # naive 本地墙钟：isoformat() 不带 +HH:MM 偏移，避免 DST 漂移
    now = datetime.now()
    start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start <= now:
        start = start + timedelta(days=1)
    return start


def _next_hourly_start_boundary(
    minute: int, *, now: datetime | None = None
) -> datetime:
    """下一本地整点后 minute 分（一小时内）。

    本小时该分仍在未来则用本小时，否则进一小时；秒与微秒置零。
    ``now`` 可注入便于测试，默认本地墙钟。

    返回值必须是 naive 本地墙钟：带 UTC 偏移会让 StartBoundary 触发
    Task Scheduler 2.0 的“跨时区同步”语义，DST 切换后逐次漂移 1 小时。
    """
    if now is None:
        # naive 本地墙钟：isoformat() 不带 +HH:MM 偏移，避免 DST 漂移
        now = datetime.now()
    elif now.tzinfo is not None:
        # 注入的是 aware 带时区对象：归一为 naive 本地墙钟，理由同上。
        # 视为已纠正：此前此处逻辑相反（把 naive 转 aware），会让
        # isoformat() 带上 offset，引发 DST 漂移。naive 输入直接使用。
        now = now.astimezone().replace(tzinfo=None)
    start = now.replace(minute=minute, second=0, microsecond=0)
    if start <= now:
        start = start + timedelta(hours=1)
    return start


def _com_normalize_hresult(value: int | str | bytes | bytearray | None) -> int | None:
    if value is None:
        return None
    try:
        # signed HRESULTs (e.g. -2147024894) → unsigned 0x80070002
        return int(value) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None


def _com_hresult(exc: BaseException) -> int | None:
    """Primary display HRESULT (outer). Does not dig into excepinfo."""
    hresult = getattr(exc, "hresult", None)
    if hresult is not None:
        hr = _com_normalize_hresult(hresult)
        if hr is not None:
            return hr
    args = getattr(exc, "args", None)
    if args:
        try:
            return _com_normalize_hresult(args[0])
        except IndexError:
            return None
    return None


def _com_excepinfo_scode(exc: BaseException) -> int | None:
    """Nested scode from pywintypes.com_error excepinfo (attr or args[2])."""
    excepinfo = getattr(exc, "excepinfo", None)
    if excepinfo is None:
        args = getattr(exc, "args", None)
        if args and len(args) >= 3:
            excepinfo = args[2]
    if not isinstance(excepinfo, (tuple, list)) or len(excepinfo) < 6:
        return None
    # (wCode, source, description, helpfile, helpContext, scode)
    return _com_normalize_hresult(excepinfo[5])


def _com_is_not_found(exc: BaseException) -> bool:
    """COM/计划任务报任务或文件夹不存在时为 True。"""
    not_found = (
        0x80070002,  # 文件不存在
        0x80070003,  # 路径不存在
    )
    task_not_ready = 0x8004130A  # 任务未就绪，勿当 missing

    hr = _com_hresult(exc)
    if hr in not_found:
        return True
    if hr == task_not_ready:
        return False

    # DISP_E_EXCEPTION (0x80020009) 等外层 HRESULT 下，真实错误在 excepinfo scode
    nested = _com_excepinfo_scode(exc)
    if nested in not_found:
        return True
    if nested == task_not_ready:
        return False

    msg = str(exc).lower()
    return (
        "cannot find" in msg
        or "not found" in msg
        or "does not exist" in msg
        or "找不到" in str(exc)
    )


def _macos_is_not_found(stderr: str) -> bool:
    return (
        "Could not find" in stderr
        or "No such process" in stderr
        or "not found" in stderr.lower()
    )


class SystemSchedulerBackend(ABC):
    """OS 级用户唤醒后端抽象。"""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台标识：'windows' | 'macos' | 'linux'。"""

    @abstractmethod
    def build_identifier(self, task_id: str) -> str:
        """构建 OS 侧任务标识。"""

    @abstractmethod
    def register(self, spec: NativeTaskSpec) -> None:
        """注册或更新（create-or-update）。"""

    @abstractmethod
    def unregister(self, task_id: str) -> None:
        """删除已注册任务。

        推荐幂等：任务已被外部途径删除时静默成功，避免 disable/pause/delete
        流程在状态漂移下被阻塞。各后端可自行决定「真正不存在」的判定。
        """

    @abstractmethod
    def list_registered_task_ids(self) -> list[str]:
        """列出本机已注册的 MWU 任务 UUID；目录/列表不存在时返回空列表。"""


class WindowsBackend(SystemSchedulerBackend):
    """Windows 计划任务后端（用户级 InteractiveToken）。"""

    platform_name = "windows"
    _FOLDER = "\\MWU"

    def build_identifier(self, task_id: str) -> str:
        return f"\\MWU\\{task_id}"

    def register(self, spec: NativeTaskSpec) -> None:
        validate_task_id(spec.task_id)
        pythoncom, Dispatch = self._import_com()
        # COM 初始化是线程级的，必须与 CoUninitialize 在同一调用内成对
        pythoncom.CoInitialize()
        service = folder = task_def = None
        try:
            service = Dispatch("Schedule.Service")
            service.Connect()
            folder = self._ensure_mwu_folder(service)
            task_def = self._build_task_definition(service, spec)
            try:
                folder.RegisterTaskDefinition(
                    spec.task_id,
                    task_def,
                    _TASK_CREATE_OR_UPDATE,
                    "",
                    "",
                    _TASK_LOGON_INTERACTIVE_TOKEN,
                )
            except Exception as e:
                raise RuntimeError(
                    f"Task Scheduler 注册失败: {self._com_error_detail(e)}"
                ) from e
            logger.info("Windows 任务注册成功: %s", self.build_identifier(spec.task_id))
        finally:
            # 释放 COM 代理引用后再 CoUninitialize，避免 IUnknown 释放告警
            service = folder = task_def = None
            pythoncom.CoUninitialize()

    def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        pythoncom, Dispatch = self._import_com()
        pythoncom.CoInitialize()
        service = folder = None
        try:
            service = Dispatch("Schedule.Service")
            service.Connect()
            try:
                folder = service.GetFolder(self._FOLDER)
            except Exception as e:
                raise RuntimeError(
                    f"Task Scheduler GetFolder 失败: {self._com_error_detail(e)}"
                ) from e
            try:
                folder.DeleteTask(task_id, 0)
            except Exception as e:
                if _com_is_not_found(e):
                    # 任务已通过 Task Scheduler GUI / 系统清理等外部途径被删除：
                    # 视为成功，避免 disable/pause/delete 流程被孤儿状态阻塞
                    logger.warning("Windows 任务 %s 已不存在，幂等视为已注销", task_id)
                    return
                raise RuntimeError(
                    f"Task Scheduler 删除失败: {self._com_error_detail(e)}"
                ) from e
        finally:
            service = folder = None
            pythoncom.CoUninitialize()

    def list_registered_task_ids(self) -> list[str]:
        pythoncom, Dispatch = self._import_com()
        pythoncom.CoInitialize()
        service = folder = tasks = None
        try:
            service = Dispatch("Schedule.Service")
            service.Connect()
            try:
                folder = service.GetFolder(self._FOLDER)
            except Exception as e:
                if _com_is_not_found(e):
                    return []
                raise RuntimeError(
                    f"Task Scheduler GetFolder 失败: {self._com_error_detail(e)}"
                ) from e
            try:
                tasks = folder.GetTasks(0)
            except Exception as e:
                raise RuntimeError(
                    f"Task Scheduler GetTasks 失败: {self._com_error_detail(e)}"
                ) from e
            ids: list[str] = []
            # COM 集合下标从 1 开始
            count = int(tasks.Count)
            for i in range(1, count + 1):
                task = None
                try:
                    task = tasks.Item(i)
                    name = str(task.Name)
                except Exception as e:
                    raise RuntimeError(
                        f"Task Scheduler 枚举任务失败 (index={i}): "
                        f"{self._com_error_detail(e)}"
                    ) from e
                finally:
                    task = None
                if _TASK_ID_RE.match(name):
                    ids.append(name)
            return ids
        finally:
            service = folder = tasks = None
            pythoncom.CoUninitialize()

    @staticmethod
    def _import_com():
        """延迟导入 pywin32，避免非 Windows 平台 import 本模块失败。"""
        try:
            import pythoncom  # type: ignore[import-not-found]
            from win32com.client import Dispatch  # type: ignore[import-not-found]
        except ImportError as e:
            raise RuntimeError(
                "Windows Task Scheduler 需要 pywin32（仅 win32 依赖）"
            ) from e
        return pythoncom, Dispatch

    @staticmethod
    def _com_error_detail(exc: BaseException) -> str:
        hr = _com_hresult(exc)
        if hr is not None:
            return f"0x{hr:08X}: {exc}"
        return str(exc)

    def _ensure_mwu_folder(self, service):
        try:
            return service.GetFolder(self._FOLDER)
        except Exception as e:
            if not _com_is_not_found(e):
                raise RuntimeError(
                    f"Task Scheduler GetFolder(\\MWU) 失败: {self._com_error_detail(e)}"
                ) from e
        try:
            root = service.GetFolder("\\")
            return root.CreateFolder("MWU")
        except Exception as e:
            raise RuntimeError(
                f"Task Scheduler CreateFolder(MWU) 失败: {self._com_error_detail(e)}"
            ) from e

    def _build_task_definition(self, service, spec: NativeTaskSpec):
        """构建 ITaskDefinition，语义对齐旧 schtasks XML。"""
        task_def = service.NewTask(0)

        task_def.RegistrationInfo.Description = f"MWU Scheduled Task: {spec.task_name}"

        principal = task_def.Principal
        principal.LogonType = _TASK_LOGON_INTERACTIVE_TOKEN

        settings = task_def.Settings
        settings.Enabled = True
        settings.StartWhenAvailable = True
        settings.AllowDemandStart = True
        settings.ExecutionTimeLimit = "PT2H"
        settings.MultipleInstances = _TASK_INSTANCES_PARALLEL
        # Task Scheduler 2.0 中 DisallowStartIfOnBatteries 与 StopIfGoingOnBatteries
        # 默认均为 VARIANT_TRUE：前者会让笔记本在电池供电时静默不触发计划任务，
        # 后者会在用户拔掉电源瞬间杀死正在运行的任务。两者必须显式置 False，
        # 否则电池供电下该功能形同虚设，且没有任何错误暴露出来。
        settings.DisallowStartIfOnBatteries = False
        settings.StopIfGoingOnBatteries = False

        self._configure_triggers(task_def.Triggers, to_schtasks(spec.cron))

        action = task_def.Actions.Create(_TASK_ACTION_EXEC)
        action.Path = spec.exe_path
        action.Arguments = windows_join_args(spec.cli_args)
        action.WorkingDirectory = spec.working_dir

        return task_def

    def _configure_triggers(self, triggers, sch: SchtasksSpec) -> None:
        schedule = sch.schedule.upper()
        hour, minute = _parse_hhmm(sch.start_time)

        if schedule == "HOURLY":
            trigger = triggers.Create(_TASK_TRIGGER_TIME)
            trigger.StartBoundary = _next_hourly_start_boundary(minute).isoformat(
                timespec="seconds"
            )
            trigger.Enabled = True
            trigger.Repetition.Interval = "PT1H"
            trigger.Repetition.StopAtDurationEnd = False
            return

        start_boundary = _next_start_boundary(hour, minute).isoformat(
            timespec="seconds"
        )

        if schedule == "DAILY":
            trigger = triggers.Create(_TASK_TRIGGER_DAILY)
            trigger.StartBoundary = start_boundary
            trigger.Enabled = True
            trigger.DaysInterval = 1
            return

        if schedule == "WEEKLY":
            if not sch.day_of_week:
                raise ValueError("weekly 触发器缺少 day_of_week")
            day_bits = _SCHTASKS_DOW_TO_COM.get(sch.day_of_week)
            if day_bits is None:
                raise ValueError(f"无效的 day_of_week: {sch.day_of_week!r}")
            trigger = triggers.Create(_TASK_TRIGGER_WEEKLY)
            trigger.StartBoundary = start_boundary
            trigger.Enabled = True
            trigger.DaysOfWeek = day_bits
            trigger.WeeksInterval = 1
            return

        if schedule == "MONTHLY":
            if sch.day_of_month is None:
                raise ValueError("monthly 触发器缺少 day_of_month")
            day = int(sch.day_of_month)
            if day < 1 or day > 31:
                raise ValueError(f"无效的 day_of_month: {day}")
            if sch.months:
                month_bits = _SCHTASKS_MONTH_TO_COM.get(sch.months)
                if month_bits is None:
                    raise ValueError(f"无效的 months: {sch.months!r}")
            else:
                month_bits = _ALL_MONTHS_COM
            trigger = triggers.Create(_TASK_TRIGGER_MONTHLY)
            trigger.StartBoundary = start_boundary
            trigger.Enabled = True
            trigger.DaysOfMonth = 1 << (day - 1)
            trigger.MonthsOfYear = month_bits
            return

        raise ValueError(f"不支持的 schtasks schedule: {schedule}")


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
        # 更新 = bootout 再 bootstrap（非并发锁）
        self._bootstrap(label, str(plist_path))
        logger.info("macOS launchd 任务注册成功: %s", label)

    def unregister(self, task_id: str) -> None:
        """删除 launchd 作业与 plist。

        幂等：bootout 报任务不存在且无残留 plist 时视为已注销（任务已被
        外部途径删除），与 ABC 契约及 WindowsBackend 一致。bootout 成功或
        「未加载但有 plist」均清理 plist；其他 bootout 错误保留 plist 并
        抛 RuntimeError；plist 删除 PermissionError 仍抛 RuntimeError。
        """
        validate_task_id(task_id)
        label = self.build_identifier(task_id)
        plist_path = self._plist_path(task_id)
        domain = self._domain()
        proc = _run_text(["launchctl", "bootout", f"{domain}/{label}"])
        plist_exists = os.path.exists(str(plist_path))

        if proc.returncode != 0:
            stderr = proc.stderr or ""
            if _macos_is_not_found(stderr) or proc.returncode == 113:
                if not plist_exists:
                    # 任务已被外部途径删除（用户 `launchctl bootout` / 删除 plist /
                    # GUI 清理等）：视为成功，避免 disable/pause/delete 流程被
                    # 孤儿状态阻塞
                    logger.warning(
                        "macOS launchd 任务 %s 已不存在，幂等视为已注销", label
                    )
                    return
                # 未加载但残留 plist，下方清理
            else:
                detail = stderr.strip() or str(proc.returncode)
                raise RuntimeError(f"launchctl bootout failed: {detail}")

        if os.path.exists(str(plist_path)):
            try:
                os.unlink(str(plist_path))
            except PermissionError as e:
                raise RuntimeError(f"无法删除 plist: {plist_path}") from e

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

    def _bootstrap(self, label: str, plist_path_str: str) -> None:
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


class LinuxBackend(SystemSchedulerBackend):
    """Linux 用户 crontab 后端。"""

    platform_name = "linux"
    _MWU_MARKER_RE = re.compile(r"^#\s*MWU:([a-f0-9-]{36})\s*$")

    def build_identifier(self, task_id: str) -> str:
        return f"# MWU:{task_id}"

    def register(self, spec: NativeTaskSpec) -> None:
        validate_task_id(spec.task_id)
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

    def unregister(self, task_id: str) -> None:
        validate_task_id(task_id)
        self._remove_from_user_crontab(task_id)

    def list_registered_task_ids(self) -> list[str]:
        text = self._read_crontab()
        return _MWU_CRON_MARKER_RE.findall(text)

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

    def _remove_from_user_crontab(self, task_id: str) -> None:
        """从用户 crontab 删除指定任务。

        幂等：crontab 为空或缺该 marker 时视为已注销（任务已被外部途径
        删除），与 ABC 契约及 WindowsBackend 一致。``crontab -l`` /
        ``crontab -`` / ``crontab -r`` 的真实失败仍抛 RuntimeError。
        """
        crontab_text = self._read_crontab()
        if not crontab_text:
            # 无 crontab 亦无 marker：任务已被外部途径删除，视为成功
            logger.warning("Linux crontab 任务 %s 已不存在，幂等视为已注销", task_id)
            return
        lines = crontab_text.splitlines(True)
        new_lines: list[str] = []
        skip_next = False
        found = False
        for line in lines:
            stripped = line.strip()
            if self._MWU_MARKER_RE.match(stripped):
                m = self._MWU_MARKER_RE.match(stripped)
                if m and m.group(1) == task_id:
                    found = True
                    skip_next = True
                    continue
            if skip_next:
                skip_next = False
                continue
            new_lines.append(line)

        if not found:
            # marker 不在 crontab 中：任务已被外部途径删除（手动编辑或
            # `crontab -r`），视为成功，避免 disable/pause/delete 流程被阻塞
            logger.warning("Linux crontab 任务 %s 已不存在，幂等视为已注销", task_id)
            return

        new_crontab = "".join(new_lines)
        if not new_crontab.strip():
            proc = _run_text(["crontab", "-r"])
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                raise RuntimeError(f"crontab -r failed: {stderr or proc.returncode}")
        else:
            self._write_crontab(new_crontab)

    def _build_command_body(self, spec: NativeTaskSpec) -> str:
        wd = shlex.quote(spec.working_dir)
        exe = shlex.quote(spec.exe_path)
        args = " ".join(shlex.quote(a) for a in spec.cli_args)
        return f"cd {wd} && {exe} {args}".rstrip()

    def _build_cron_line(self, spec: NativeTaskSpec) -> str:
        return f"{to_crontab_line(spec.cron)} {self._build_command_body(spec)}"


def get_backend(platform_name: str | None = None) -> SystemSchedulerBackend:
    """按平台返回对应后端实例。"""
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
    """构造源码/冻结包下的 OS 注册命令。"""
    import sys

    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen

    if is_frozen:
        return sys.executable, ["--scheduled-task", task_id]
    main_py = str((Path(app_root) / "main.py").resolve())
    return sys.executable, [main_py, "--scheduled-task", task_id]
