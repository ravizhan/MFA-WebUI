"""
OS 级调度器后端 —— 策略模式实现。
支持 Windows (schtasks)、macOS (launchd)、Linux (crontab)。
"""

import asyncio
import logging
import os
import platform
import plistlib
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional, Union, cast

from models.scheduler import (
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    OSTriggerSpec,
    SystemTaskScope,
    SystemTaskSpec,
    TriggerConfig,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_TASK_ID_RE = re.compile(r"^[a-f0-9-]{36}$")

# Windows Task Scheduler 命名空间
_XML_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"

# cron 5-field 正则（简单校验）
_CRON_FIELD_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$")

# 星期名称映射：cron weekday 到 Windows DayOfWeek 元素名
_CRON_DOW_TO_WINDOWS = {
    "0": "Sunday",
    "7": "Sunday",
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
}
# cron weekday 到编号 (0=Sunday, 6=Saturday)
_CRON_DOW_TO_NUM = {"0": 0, "7": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_uid() -> int:
    """获取当前用户 UID（Windows 上返回 0）。"""
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid else 0


def validate_task_id(task_id: str) -> None:
    """验证 task_id 为合法 UUID 格式，防止命令注入。

    Raises:
        ValueError: task_id 格式不合法
    """
    if not _TASK_ID_RE.match(task_id):
        raise ValueError(
            f"无效的 task_id 格式: {task_id!r}，必须是标准 UUID 格式（36 位十六进制+连字符）"
        )


def _parse_cron_fields(expr: str) -> dict:
    """将 5-field cron 表达式解析为字段字典。

    Args:
        expr: 5-field cron 表达式，如 "0 9 * * *"

    Returns:
        {"minute": ..., "hour": ..., "day": ..., "month": ..., "weekday": ...}

    Raises:
        ValueError: 表达式格式不正确
    """
    m = _CRON_FIELD_RE.match(expr.strip())
    if not m:
        raise ValueError(f"无效的 cron 表达式（需要 5 个字段）: {expr!r}")
    return {
        "minute": m.group(1),
        "hour": m.group(2),
        "day": m.group(3),
        "month": m.group(4),
        "weekday": m.group(5),
    }


def _parse_cron_field_list(value: str, max_val: int) -> list[int]:
    """将 cron 字段值展开为整数列表，支持 *、*/N、逗号分隔、单个值。

    Args:
        value: cron 字段原始字符串
        max_val: 该字段的最大值（用于展开 *）
    """
    if value == "*":
        return list(range(0, max_val + 1))

    results: list[int] = []
    parts = value.split(",")
    for part in parts:
        part = part.strip()
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            if base == "*":
                base_start, base_end = 0, max_val
            elif "-" in base:
                lo, hi = base.split("-", 1)
                base_start, base_end = int(lo), int(hi)
            else:
                base_start, base_end = int(base), max_val
            for v in range(base_start, base_end + 1, step):
                if v not in results:
                    results.append(v)
        elif "-" in part:
            lo, hi = part.split("-", 1)
            for v in range(int(lo), int(hi) + 1):
                if v not in results:
                    results.append(v)
        else:
            v = int(part)
            if v not in results:
                results.append(v)
    return sorted(results)


# ---------------------------------------------------------------------------
# Trigger 映射
# ---------------------------------------------------------------------------


def map_trigger_to_os_spec(trigger_config: TriggerConfig) -> OSTriggerSpec:
    """将 APScheduler 触发器配置映射为 OS 级触发器规格。

    Args:
        trigger_config: CronTriggerConfig | DateTriggerConfig | IntervalTriggerConfig

    Returns:
        OSTriggerSpec

    Raises:
        ValueError: DateTrigger 已过期或无法映射
    """
    if isinstance(trigger_config, CronTriggerConfig):
        return OSTriggerSpec(
            trigger_type="cron",
            cron_expression=trigger_config.cron,
        )
    elif isinstance(trigger_config, DateTriggerConfig):
        if trigger_config.run_date <= datetime.now():
            raise ValueError("DateTrigger 已过期，无法注册")
        return OSTriggerSpec(
            trigger_type="date",
            run_date=trigger_config.run_date,
        )
    elif isinstance(trigger_config, IntervalTriggerConfig):
        # 计算总分钟数：秒级向上取整到分钟
        weeks = trigger_config.weeks or 0
        days = trigger_config.days or 0
        hours = trigger_config.hours or 0
        minutes = trigger_config.minutes or 0
        seconds = trigger_config.seconds or 0

        total_minutes = weeks * 7 * 24 * 60 + days * 24 * 60 + hours * 60 + minutes
        if seconds > 0:
            total_minutes += 1  # 有秒数则向上取整

        # 至少 1 分钟
        if total_minutes < 1:
            total_minutes = 1

        return OSTriggerSpec(
            trigger_type="interval",
            interval_minutes=total_minutes,
        )
    else:
        raise TypeError(f"未知的触发器类型: {type(trigger_config)}")


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------


class SystemSchedulerBackend(ABC):
    """OS 级调度器后端抽象基类"""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """返回平台标识: 'windows' | 'macos' | 'linux'"""

    @abstractmethod
    async def register(self, spec: SystemTaskSpec) -> None:
        """幂等注册：已存在则更新。若 scope=SYSTEM 需提权，提权失败抛 PermissionError"""

    @abstractmethod
    async def unregister(self, task_id: str, scope: SystemTaskScope) -> None:
        """幂等卸载：不存在则静默成功"""

    @abstractmethod
    async def is_registered(self, task_id: str, scope: SystemTaskScope) -> bool:
        """查询注册状态"""

    @abstractmethod
    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        """查询 OS 报告的下次运行时间"""

    @abstractmethod
    async def list_registered(self) -> list[str]:
        """列出所有 MWU 注册的系统任务 ID"""


# ---------------------------------------------------------------------------
# Windows 后端
# ---------------------------------------------------------------------------


class WindowsBackend(SystemSchedulerBackend):
    """Windows Task Scheduler 后端，使用 schtasks /create /xml 方式注册。"""

    platform_name = "windows"

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def register(self, spec: SystemTaskSpec) -> None:
        """幂等注册任务到 Windows Task Scheduler。"""
        validate_task_id(spec.task_id)

        xml_bytes = self._build_task_xml(spec)
        temp_path = None
        try:
            # 写入临时 XML 文件
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
                f.write(xml_bytes)
                temp_path = f.name

            task_path = f"\\MWU\\{spec.task_id}"

            if spec.scope == SystemTaskScope.USER:
                await asyncio.to_thread(
                    self._run_schtasks,
                    ["schtasks", "/create", "/xml", temp_path, "/tn", task_path, "/f"],
                    check=True,
                )
            else:
                await self._run_as_admin(
                    f'/create /xml "{temp_path}" /tn "{task_path}" /f'
                )
            logger.info(
                "Windows 任务注册成功: %s (scope=%s)", task_path, spec.scope.value
            )

        except subprocess.CalledProcessError as e:
            stderr = (
                (e.stderr or b"").decode("utf-8", errors="replace") if e.stderr else ""
            )
            raise RuntimeError(f"schtasks 注册失败: {stderr.strip() or e}") from e
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    async def unregister(self, task_id: str, scope: SystemTaskScope) -> None:
        """幂等卸载。"""
        validate_task_id(task_id)
        task_path = f"\\MWU\\{task_id}"

        if scope == SystemTaskScope.USER:
            proc = await asyncio.to_thread(
                subprocess.run,
                ["schtasks", "/delete", "/tn", task_path, "/f"],
                capture_output=True,
            )
            if proc.returncode != 0:
                stderr = cast(bytes, proc.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                # 任务不存在时静默
                if (
                    "ERROR: The system cannot find the file specified" not in stderr
                    and "does not exist" not in stderr.lower()
                ):
                    logger.warning("schtasks 卸载异常: %s", stderr.strip())
        else:
            await self._run_as_admin(f'/delete /tn "{task_path}" /f', check=False)

    async def is_registered(self, task_id: str, scope: SystemTaskScope) -> bool:
        """查询任务是否已注册。"""
        validate_task_id(task_id)
        task_path = f"\\MWU\\{task_id}"
        proc = await asyncio.to_thread(
            subprocess.run,
            ["schtasks", "/query", "/tn", task_path, "/fo", "list"],
            capture_output=True,
        )
        return proc.returncode == 0

    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        """从 schtasks 输出中解析下次运行时间。"""
        validate_task_id(task_id)
        task_path = f"\\MWU\\{task_id}"
        proc = await asyncio.to_thread(
            subprocess.run,
            ["schtasks", "/query", "/tn", task_path, "/fo", "list", "/v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            return None

        output = cast(str, proc.stdout or "")
        # 中英文支持
        for line in output.splitlines():
            stripped = line.strip()
            if (
                "下次运行时间:" in stripped
                or "Next Run Time:" in stripped
                or "Next Run:" in stripped
            ):
                # 提取冒号后的部分
                _, _, value = stripped.partition(":")
                value = value.strip()
                if not value or value in ("N/A", "Disabled", "无"):
                    return None
                # 尝试多种时间格式
                for fmt in (
                    "%Y/%m/%d %H:%M:%S",
                    "%Y-%m-%d %H:%M:%S",
                    "%m/%d/%Y %H:%M:%S",
                    "%Y/%m/%d %H:%M",
                    "%Y-%m-%dT%H:%M:%S",
                ):
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue
                return None
        return None

    async def list_registered(self) -> list[str]:
        """列出所有 \\MWU\\ 下的任务，提取 task_id。"""
        proc = await asyncio.to_thread(
            subprocess.run,
            ["schtasks", "/query", "/fo", "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            return []

        task_ids: list[str] = []
        pattern = re.compile(r"\\MWU\\([a-f0-9-]{36})")
        for line in cast(str, proc.stdout or "").splitlines():
            m = pattern.search(line)
            if m:
                tid = m.group(1)
                if tid not in task_ids:
                    task_ids.append(tid)
        return task_ids

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    @staticmethod
    def _run_schtasks(
        args: list[str], check: bool = True
    ) -> subprocess.CompletedProcess:
        """运行 schtasks 命令。"""
        return subprocess.run(args, capture_output=True, check=check)

    async def _run_as_admin(self, schtasks_args: str, check: bool = True) -> None:
        """以管理员权限运行 schtasks（通过 ShellExecuteW + runas 触发 UAC）。"""
        import ctypes

        # 先检查是否已是管理员
        if ctypes.windll.shell32.IsUserAnAdmin():
            # 已是管理员，直接运行
            result = await asyncio.to_thread(
                subprocess.run,
                f"schtasks {schtasks_args}",
                capture_output=True,
                shell=True,
            )
            if check and result.returncode != 0:
                stderr = cast(bytes, result.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                raise RuntimeError(f"schtasks 执行失败: {stderr.strip()}")
            return

        # 需要提权：使用 ShellExecuteW + runas
        ret = await asyncio.to_thread(
            ctypes.windll.shell32.ShellExecuteW,
            None,  # hwnd
            "runas",  # 触发 UAC 提权
            "schtasks",
            schtasks_args,
            None,  # working directory
            1,  # SW_SHOWNORMAL
        )

        if ret <= 32:
            # 用户取消了 UAC 或出错
            error_codes = {
                0: "内存不足",
                2: "文件未找到",
                3: "路径未找到",
                5: "拒绝访问",
                120: "已取消",
            }
            msg = error_codes.get(ret, f"错误码 {ret}")
            if check:
                raise PermissionError(
                    f"系统级注册需要管理员权限，用户取消了授权 ({msg})"
                )
            logger.warning("提权操作被取消 (ShellExecuteW 返回值 %d)", ret)

    def _build_task_xml(self, spec: SystemTaskSpec) -> bytes:
        """构建 schtasks 导入所需的 XML。"""
        ET.register_namespace("", _XML_NS)
        root = ET.Element(f"{{{_XML_NS}}}Task")

        # RegistrationInfo
        ri = ET.SubElement(root, "RegistrationInfo")
        desc = ET.SubElement(ri, "Description")
        desc.text = f"MWU Scheduled Task: {spec.task_name}"
        uri = ET.SubElement(ri, "URI")
        uri.text = f"\\MWU\\{spec.task_id}"

        # Principals
        principals = ET.SubElement(root, "Principals")
        principal = ET.SubElement(principals, "Principal")
        principal.set("id", "Author")
        if spec.scope == SystemTaskScope.SYSTEM:
            uid = ET.SubElement(principal, "UserId")
            uid.text = "S-1-5-18"
            lt = ET.SubElement(principal, "LogonType")
            lt.text = "ServiceAccount"
        else:
            lt = ET.SubElement(principal, "LogonType")
            lt.text = "InteractiveToken"

        # Triggers
        triggers = ET.SubElement(root, "Triggers")
        self._add_triggers(triggers, spec.trigger)

        # Actions
        actions = ET.SubElement(root, "Actions")
        exec_el = ET.SubElement(actions, "Exec")
        cmd = ET.SubElement(exec_el, "Command")
        cmd.text = spec.exe_path
        args = ET.SubElement(exec_el, "Arguments")
        args.text = " ".join(spec.cli_args)
        wd = ET.SubElement(exec_el, "WorkingDirectory")
        wd.text = spec.working_dir

        # Settings
        settings = ET.SubElement(root, "Settings")
        swa = ET.SubElement(settings, "StartWhenAvailable")
        swa.text = "true"
        etl = ET.SubElement(settings, "ExecutionTimeLimit")
        etl.text = "PT2H"
        mip = ET.SubElement(settings, "MultipleInstancesPolicy")
        mip.text = "IgnoreNew"

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _add_triggers(self, parent: ET.Element, trigger_spec: OSTriggerSpec) -> None:
        """根据触发规格添加 Trigger 元素到 XML 树。"""
        if trigger_spec.trigger_type == "date":
            trigger = ET.SubElement(parent, "TimeTrigger")
            sb = ET.SubElement(trigger, "StartBoundary")
            if trigger_spec.run_date is None:
                raise ValueError("date 类型的触发器缺少 run_date")
            sb.text = trigger_spec.run_date.isoformat()
            return

        if trigger_spec.trigger_type == "interval":
            trigger = ET.SubElement(parent, "CalendarTrigger")
            sb = ET.SubElement(trigger, "StartBoundary")
            sb.text = datetime.now().isoformat()
            schedule_by_day = ET.SubElement(trigger, "ScheduleByDay")
            days_interval = ET.SubElement(schedule_by_day, "DaysInterval")
            days_interval.text = "1"
            rep = ET.SubElement(trigger, "Repetition")
            interval = ET.SubElement(rep, "Interval")
            interval.text = f"PT{trigger_spec.interval_minutes}M"
            return

        # cron
        if not trigger_spec.cron_expression:
            raise ValueError("cron 类型的触发器缺少 cron_expression")
        fields = _parse_cron_fields(trigger_spec.cron_expression)

        day_val = fields["day"]
        dow_val = fields["weekday"]
        day_restricted = day_val != "*"
        dow_restricted = dow_val != "*"

        if day_restricted and dow_restricted:
            raise ValueError("Windows 不支持 day-of-month 和 day-of-week 同时限制")

        trigger = ET.SubElement(parent, "CalendarTrigger")
        sb = ET.SubElement(trigger, "StartBoundary")
        sb.text = datetime.now().isoformat()

        if dow_restricted:
            # 按星期调度
            schedule_by_week = ET.SubElement(trigger, "ScheduleByWeek")
            days_of_week = ET.SubElement(schedule_by_week, "DaysOfWeek")
            for dow in _parse_cron_field_list(dow_val, 7):
                element_name = _CRON_DOW_TO_WINDOWS.get(str(dow), "Sunday")
                ET.SubElement(days_of_week, element_name)
            weeks_interval = ET.SubElement(schedule_by_week, "WeeksInterval")
            weeks_interval.text = "1"
        elif day_restricted:
            # 按月调度
            schedule_by_month = ET.SubElement(trigger, "ScheduleByMonth")
            days_of_month = ET.SubElement(schedule_by_month, "DaysOfMonth")
            for d in _parse_cron_field_list(day_val, 31):
                day_el = ET.SubElement(days_of_month, "Day")
                day_el.text = str(d)
            months_el = ET.SubElement(schedule_by_month, "Months")
            # 月份处理
            month_val = fields["month"]
            if month_val == "*":
                for m in range(1, 13):
                    month = ET.SubElement(months_el, "Month")
                    month.text = str(m)
            else:
                for m in _parse_cron_field_list(month_val, 12):
                    month = ET.SubElement(months_el, "Month")
                    month.text = str(m)
        else:
            # 每天
            schedule_by_day = ET.SubElement(trigger, "ScheduleByDay")
            days_interval = ET.SubElement(schedule_by_day, "DaysInterval")
            days_interval.text = "1"

        # 时间重复
        rep = ET.SubElement(trigger, "Repetition")
        interval = ET.SubElement(rep, "Interval")
        interval.text = "PT1M"
        duration = ET.SubElement(rep, "Duration")
        duration.text = "P1D"


# ---------------------------------------------------------------------------
# macOS 后端
# ---------------------------------------------------------------------------


class MacOSBackend(SystemSchedulerBackend):
    """macOS 14+ launchd 后端，使用 launchctl bootstrap / bootout。"""

    platform_name = "macos"

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    @staticmethod
    def _plist_label(task_id: str, scope: SystemTaskScope) -> str:
        """返回 launchd label。"""
        if scope == SystemTaskScope.SYSTEM:
            return f"com.mwu.daemon.{task_id}"
        return f"com.mwu.task.{task_id}"

    @staticmethod
    def _plist_path(task_id: str, scope: SystemTaskScope) -> Path:
        """返回 plist 文件路径。"""
        label = MacOSBackend._plist_label(task_id, scope)
        if scope == SystemTaskScope.SYSTEM:
            return Path(f"/Library/LaunchDaemons/{label}.plist")
        return Path(f"~/Library/LaunchAgents/{label}.plist").expanduser()

    def _domain(self, scope: SystemTaskScope) -> str:
        """返回 launchd domain。

        系统级用 "system"（仅 macOS 13+ launchctl 支持此简写，14+ bootstrap 也能接受）。
        对于 `launchctl list`，系统服务直接使用 "system/" 前缀或通过 plist 路径识别。
        """
        if scope == SystemTaskScope.SYSTEM:
            return "system"
        return f"gui/{_get_uid()}"

    async def register(self, spec: SystemTaskSpec) -> None:
        """幂等注册到 launchd。"""
        validate_task_id(spec.task_id)
        label = self._plist_label(spec.task_id, spec.scope)
        plist_path = self._plist_path(spec.task_id, spec.scope)

        # 构建 plist
        plist_data = self._build_plist(spec)

        if spec.scope == SystemTaskScope.USER:
            # 确保目录存在
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            # 写入 plist
            await asyncio.to_thread(self._write_plist, plist_path, plist_data)
            # bootstrap
            await self._bootstrap_idempotent(label, str(plist_path), spec.scope)
        else:
            # 系统级：通过 osascript 提权
            plist_xml = await asyncio.to_thread(plistlib.dumps, plist_data)
            plist_xml_str = plist_xml.decode("utf-8")
            await self._run_osascript_admin(
                self._admin_register_script(str(plist_path), label, plist_xml_str)
            )
        logger.info(
            "macOS launchd 任务注册成功: %s (scope=%s)", label, spec.scope.value
        )

    async def unregister(self, task_id: str, scope: SystemTaskScope) -> None:
        """幂等卸载。"""
        validate_task_id(task_id)
        label = self._plist_label(task_id, scope)
        plist_path = self._plist_path(task_id, scope)

        if scope == SystemTaskScope.USER:
            domain = f"gui/{_get_uid()}"
            # bootout
            proc = await asyncio.to_thread(
                subprocess.run,
                ["launchctl", "bootout", f"{domain}/{label}"],
                capture_output=True,
            )
            if proc.returncode != 0:
                stderr = cast(bytes, proc.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                # "Could not find domain for" 表示不存在
                if "Could not find" not in stderr and "No such process" not in stderr:
                    logger.debug("launchctl bootout: %s", stderr.strip())
            # 删除 plist 文件
            if await asyncio.to_thread(os.path.exists, str(plist_path)):
                await asyncio.to_thread(os.unlink, str(plist_path))
        else:
            await self._run_osascript_admin(
                self._admin_unregister_script(str(plist_path), label)
            )

    async def is_registered(self, task_id: str, scope: SystemTaskScope) -> bool:
        """查询任务是否已注册。"""
        validate_task_id(task_id)
        label = self._plist_label(task_id, scope)
        proc = await asyncio.to_thread(
            subprocess.run,
            ["launchctl", "list", label],
            capture_output=True,
        )
        return proc.returncode == 0

    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        """launchd 不公开暴露下次运行时间，返回 None。"""
        return None

    async def list_registered(self) -> list[str]:
        """列出所有已注册的 MWU 任务。"""
        result: list[str] = []
        pattern = re.compile(r"com\.mwu\.(?:task|daemon)\.([a-f0-9-]{36})\.plist$")

        # 用户级
        agents_dir = Path("~/Library/LaunchAgents").expanduser()
        if await asyncio.to_thread(agents_dir.exists):
            agent_entries: list[Path] = cast(
                list[Path], await asyncio.to_thread(list, agents_dir.iterdir())
            )
            for entry in agent_entries:
                m = pattern.match(entry.name)
                if m:
                    tid = m.group(1)
                    if tid not in result:
                        result.append(tid)

        # 系统级（需要足够权限才能读取，可能抛异常）
        daemons_dir = Path("/Library/LaunchDaemons")
        try:
            if await asyncio.to_thread(daemons_dir.exists):
                daemon_entries: list[Path] = cast(
                    list[Path], await asyncio.to_thread(list, daemons_dir.iterdir())
                )
                for entry in daemon_entries:
                    m = pattern.match(entry.name)
                    if m:
                        tid = m.group(1)
                        if tid not in result:
                            result.append(tid)
        except PermissionError:
            logger.debug("无法读取 /Library/LaunchDaemons（权限不足）")

        return result

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    @staticmethod
    def _write_plist(path: Path, data: dict) -> None:
        """写入 plist 文件。"""
        with open(path, "wb") as f:
            plistlib.dump(data, f)

    async def _bootstrap_idempotent(
        self, label: str, plist_path_str: str, scope: SystemTaskScope
    ) -> None:
        """幂等 bootstrap：已存在则先 bootout 再 bootstrap。"""
        domain = self._domain(scope)
        target = f"{domain}/{label}"

        proc = await asyncio.to_thread(
            subprocess.run,
            ["launchctl", "bootstrap", domain, plist_path_str],
            capture_output=True,
        )
        if proc.returncode == 0:
            return

        stderr = cast(bytes, proc.stderr or b"").decode("utf-8", errors="replace")
        if (
            "already bootstrapped" in stderr.lower()
            or "service already loaded" in stderr.lower()
            or "service is already" in stderr.lower()
        ):
            # 先 bootout 再 bootstrap
            await asyncio.to_thread(
                subprocess.run,
                ["launchctl", "bootout", target],
                capture_output=True,
            )
            await asyncio.to_thread(
                subprocess.run,
                ["launchctl", "bootstrap", domain, plist_path_str],
                capture_output=True,
                check=True,
            )
        else:
            raise RuntimeError(f"launchctl bootstrap 失败: {stderr.strip()}")

    def _build_plist(self, spec: SystemTaskSpec) -> dict:
        """构建 launchd plist dict。"""
        label = self._plist_label(spec.task_id, spec.scope)

        plist: dict = {
            "Label": label,
            "ProgramArguments": [spec.exe_path] + spec.cli_args,
            "WorkingDirectory": spec.working_dir,
            "RunAtLoad": False,
        }

        # 日志路径
        log_path = os.path.join(
            spec.working_dir, "config", "logs", f"headless_{spec.task_id}.log"
        )
        plist["StandardOutPath"] = log_path
        plist["StandardErrorPath"] = log_path

        trigger_spec = spec.trigger
        if trigger_spec.trigger_type == "cron":
            if not trigger_spec.cron_expression:
                raise ValueError("cron 类型的触发器缺少 cron_expression")
            fields = _parse_cron_fields(trigger_spec.cron_expression)
            sci: dict = {}
            if fields["minute"] != "*":
                sci["Minute"] = _parse_cron_field_list(fields["minute"], 59)
            if fields["hour"] != "*":
                sci["Hour"] = _parse_cron_field_list(fields["hour"], 23)
            if fields["day"] != "*":
                sci["Day"] = _parse_cron_field_list(fields["day"], 31)
            if fields["month"] != "*":
                sci["Month"] = _parse_cron_field_list(fields["month"], 12)
            if fields["weekday"] != "*":
                # cron 0/7 = Sunday，macOS 的 Weekday 也是 0=Sunday
                sci["Weekday"] = _parse_cron_field_list(fields["weekday"], 7)
            plist["StartCalendarInterval"] = sci
        elif trigger_spec.trigger_type == "date":
            dt = trigger_spec.run_date
            if dt is None:
                raise ValueError("date 类型的触发器缺少 run_date")
            plist["StartCalendarInterval"] = {
                "Minute": dt.minute,
                "Hour": dt.hour,
                "Day": dt.day,
                "Month": dt.month,
                "Year": dt.year,
            }
        elif trigger_spec.trigger_type == "interval":
            plist["StartInterval"] = (trigger_spec.interval_minutes or 0) * 60

        return plist

    async def _run_osascript_admin(self, script: str) -> None:
        """通过 osascript 以管理员权限运行 shell 脚本。"""
        apple_script = f'do shell script "{script}" with administrator privileges'
        proc = await asyncio.to_thread(
            subprocess.run,
            ["osascript", "-e", apple_script],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            stderr = cast(str, proc.stderr or "").strip()
            if "User cancelled" in stderr or "(-128)" in stderr:
                raise PermissionError("系统级注册需要管理员权限，用户取消了授权")
            raise RuntimeError(f"osascript 执行失败: {stderr}")

    def _admin_register_script(
        self, plist_path: str, label: str, plist_xml: str
    ) -> str:
        """生成管理员注册脚本。"""
        # 转义需要在 shell 中处理的内容
        escaped_xml = plist_xml.replace("'", "'\\''")
        escaped_path = plist_path.replace("'", "'\\''")
        script = (
            f"mkdir -p '/Library/LaunchDaemons' && "
            f"echo '{escaped_xml}' > '{escaped_path}' && "
            f"launchctl bootstrap system '{escaped_path}'"
        )
        return script

    def _admin_unregister_script(self, plist_path: str, label: str) -> str:
        """生成管理员卸载脚本。"""
        escaped_path = plist_path.replace("'", "'\\''")
        script = f"launchctl bootout system/{label} 2>/dev/null; rm -f '{escaped_path}'"
        return script


# ---------------------------------------------------------------------------
# Linux 后端
# ---------------------------------------------------------------------------


class LinuxBackend(SystemSchedulerBackend):
    """Linux crontab 后端。"""

    platform_name = "linux"

    _MWU_MARKER_RE = re.compile(r"^#\s*MWU:([a-f0-9-]{36})\s*$")

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def register(self, spec: SystemTaskSpec) -> None:
        """幂等注册到 crontab 或 /etc/cron.d（系统级）。"""
        validate_task_id(spec.task_id)

        trigger_spec = spec.trigger
        if trigger_spec.trigger_type == "date":
            raise ValueError(
                "Linux crontab 不支持一次性 DateTrigger，请使用 cron 或 interval"
            )

        if spec.scope == SystemTaskScope.USER:
            await self._register_user_cron(spec)
        else:
            await self._register_system_cron(spec)
        logger.info("Linux 任务注册成功: %s (scope=%s)", spec.task_id, spec.scope.value)

    async def unregister(self, task_id: str, scope: SystemTaskScope) -> None:
        """幂等卸载。"""
        validate_task_id(task_id)

        if scope == SystemTaskScope.USER:
            await self._remove_from_user_crontab(task_id)
        else:
            file_path = f"/etc/cron.d/mwu-{task_id}"
            proc = await asyncio.to_thread(
                subprocess.run,
                ["pkexec", "rm", "-f", file_path],
                capture_output=True,
            )
            if proc.returncode != 0:
                stderr = cast(bytes, proc.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                if (
                    "not authorized" in stderr.lower()
                    or "user cancelled" in stderr.lower()
                ):
                    pass  # 用户取消，静默
                else:
                    logger.debug("pkexec rm 失败: %s", stderr.strip())

    async def is_registered(self, task_id: str, scope: SystemTaskScope) -> bool:
        """查询任务是否已注册。"""
        validate_task_id(task_id)

        if scope == SystemTaskScope.USER:
            marker = f"# MWU:{task_id}"
            crontab_text = await self._read_crontab()
            return marker in crontab_text
        else:
            file_path = f"/etc/cron.d/mwu-{task_id}"
            return await asyncio.to_thread(os.path.exists, file_path)

    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        """crontab 不暴露下次运行时间，返回 None。"""
        return None

    async def list_registered(self) -> list[str]:
        """列出所有 MWU 注册的 crontab 任务。"""
        result: list[str] = []

        # 用户 crontab
        crontab_text = await self._read_crontab()
        for line in crontab_text.splitlines():
            m = self._MWU_MARKER_RE.match(line.strip())
            if m:
                tid = m.group(1)
                if tid not in result:
                    result.append(tid)

        # 系统级 cron.d
        cron_d_dir = "/etc/cron.d"
        pattern = re.compile(r"^mwu-([a-f0-9-]{36})$")
        try:
            if await asyncio.to_thread(os.path.exists, cron_d_dir):
                cron_entries: list[str] = cast(
                    list[str], await asyncio.to_thread(os.listdir, cron_d_dir)
                )
                for entry in cron_entries:
                    m = pattern.match(entry)
                    if m:
                        tid = m.group(1)
                        if tid not in result:
                            result.append(tid)
        except PermissionError:
            logger.debug("无法读取 /etc/cron.d（权限不足）")

        return result

    # ------------------------------------------------------------------
    # 用户级 crontab
    # ------------------------------------------------------------------

    async def _read_crontab(self) -> str:
        """读取当前用户的 crontab。"""
        proc = await asyncio.to_thread(
            subprocess.run,
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return ""  # 用户还没有 crontab
        return cast(str, proc.stdout or "")

    async def _write_crontab(self, content: str) -> None:
        """写入 crontab。"""
        proc = await asyncio.to_thread(
            subprocess.run,
            ["crontab", "-"],
            input=content,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            raise RuntimeError(f"crontab 写入失败: {stderr.strip()}")

    async def _remove_from_user_crontab(self, task_id: str) -> None:
        """从用户 crontab 中移除 MWU 条目。"""
        crontab_text = await self._read_crontab()
        if not crontab_text:
            return

        lines = crontab_text.splitlines(True)  # keep line endings
        new_lines: list[str] = []
        skip_next = False
        for line in lines:
            stripped = line.strip()
            if self._MWU_MARKER_RE.match(stripped):
                skip_next = True
                continue
            if skip_next:
                skip_next = False
                continue
            new_lines.append(line)

        new_crontab = "".join(new_lines)
        if not new_crontab.strip():
            # 删除所有内容 → 移除整个 crontab
            proc = await asyncio.to_thread(
                subprocess.run,
                ["crontab", "-r"],
                capture_output=True,
            )
            if proc.returncode != 0:
                stderr = cast(bytes, proc.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                # "no crontab for" 表示本来就没有
                if "no crontab for" not in stderr.lower():
                    logger.debug("crontab -r 失败: %s", stderr.strip())
        else:
            await self._write_crontab(new_crontab)

    async def _register_user_cron(self, spec: SystemTaskSpec) -> None:
        """注册用户级 crontab 任务。"""
        trigger_spec = spec.trigger
        cron_line = self._build_cron_line(spec)

        crontab_text = await self._read_crontab()

        # 删除旧条目
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

        # 追加新条目
        entry = f"# MWU:{spec.task_id}\n{cron_line}\n"
        new_crontab = "".join(new_lines) + entry
        await self._write_crontab(new_crontab)

    def _build_cron_line(self, spec: SystemTaskSpec) -> str:
        """构建单行 crontab 条目。"""
        trigger_spec = spec.trigger
        if trigger_spec.trigger_type == "cron":
            if not trigger_spec.cron_expression:
                raise ValueError("cron 类型的触发器缺少 cron_expression")
            cron_timing = trigger_spec.cron_expression
        elif trigger_spec.trigger_type == "interval":
            minutes = trigger_spec.interval_minutes or 1
            cron_timing = f"*/{minutes} * * * *"
        else:
            raise ValueError(f"不支持的触发器类型: {trigger_spec.trigger_type}")

        return f"{cron_timing} {spec.exe_path} {' '.join(spec.cli_args)}"

    # ------------------------------------------------------------------
    # 系统级 crontab
    # ------------------------------------------------------------------

    async def _register_system_cron(self, spec: SystemTaskSpec) -> None:
        """注册系统级 crontab 到 /etc/cron.d/mwu-{task_id}。"""
        trigger_spec = spec.trigger
        if trigger_spec.trigger_type == "cron":
            if not trigger_spec.cron_expression:
                raise ValueError("cron 类型的触发器缺少 cron_expression")
            cron_timing = trigger_spec.cron_expression
        elif trigger_spec.trigger_type == "interval":
            minutes = trigger_spec.interval_minutes or 1
            cron_timing = f"*/{minutes} * * * *"
        else:
            raise ValueError(f"不支持的触发器类型: {trigger_spec.trigger_type}")

        # /etc/cron.d 格式: timing user command
        task_path = f"/etc/cron.d/mwu-{spec.task_id}"
        content = (
            f"# MWU:{spec.task_name}\n"
            f"{cron_timing} root {spec.exe_path} {' '.join(spec.cli_args)}\n"
        )

        await self._write_via_pkexec(task_path, content)

    async def _write_via_pkexec(self, file_path: str, content: str) -> None:
        """通过 pkexec tee 写入文件。"""
        proc = await asyncio.to_thread(
            subprocess.run,
            ["pkexec", "tee", file_path],
            input=content,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            stderr = cast(str, proc.stderr or "").strip()
            if (
                "not authorized" in stderr.lower()
                or "dismissed" in stderr.lower()
                or "cancelled" in stderr.lower()
            ):
                raise PermissionError("系统级注册需要管理员权限，用户取消了授权")
            raise RuntimeError(f"pkexec 写入失败: {stderr}")


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def get_backend() -> SystemSchedulerBackend:
    """根据当前平台返回对应后端实例。

    Returns:
        SystemSchedulerBackend 具体实现

    Raises:
        RuntimeError: 不支持的平台
    """
    system = platform.system().lower()
    if system == "windows":
        return WindowsBackend()
    elif system == "darwin":
        return MacOSBackend()
    elif system == "linux":
        return LinuxBackend()
    else:
        raise RuntimeError(f"不支持的平台: {system}")
