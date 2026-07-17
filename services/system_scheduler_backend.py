"""
OS 级调度器后端 —— 策略模式实现。
支持 Windows (schtasks)、macOS (launchd)、Linux (crontab)。

Normative capability contract (no silent approximation):
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
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, cast


from models.scheduler import (
    CapabilityCell,
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
    OSTriggerSpec,
    SystemCapabilitiesResponse,
    SystemTaskScope,
    SystemTaskSpec,
    TriggerConfig,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_TASK_ID_RE = re.compile(r"^[a-f0-9-]{36}$")
_XML_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
_CRON_FIELD_RE = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$")
# Numeric fixed daily: M H * * *
_FIXED_DAILY_CRON_RE = re.compile(r"^(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*$")
# Numeric cron field pieces (no names)
_NUMERIC_CRON_TOKEN_RE = re.compile(
    r"^(\*|\d+)(-\d+)?(/\d+)?(,(\*|\d+)(-\d+)?(/\d+)?)*$"
)
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


def _parse_cron_fields(expr: str) -> dict:
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
    """Expand a numeric cron field. Names/empty/descending ranges rejected."""
    if value == "*":
        return list(range(0, max_val + 1))
    if not _NUMERIC_CRON_TOKEN_RE.match(value):
        raise ValueError(f"非数字 cron 字段不被支持: {value!r}")
    results: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"空 cron 字段片段: {value!r}")
        if "/" in part:
            base, step_s = part.split("/", 1)
            if not step_s or not step_s.isdigit():
                raise ValueError(f"无效 step: {part!r}")
            step = int(step_s)
            if step <= 0:
                raise ValueError(f"无效 step: {part!r}")
            if base == "*":
                base_start, base_end = 0, max_val
            elif "-" in base:
                lo, hi = base.split("-", 1)
                base_start, base_end = int(lo), int(hi)
                if base_start > base_end:
                    raise ValueError(f"降序 cron 范围不被支持: {part!r}")
            else:
                if base == "" or not base.lstrip("-").isdigit():
                    raise ValueError(f"无效 step base: {part!r}")
                base_start, base_end = int(base), max_val
            chunk = list(range(base_start, base_end + 1, step))
            if not chunk:
                raise ValueError(f"cron 展开为空: {part!r}")
            for v in chunk:
                if v not in results:
                    results.append(v)
        elif "-" in part:
            lo, hi = part.split("-", 1)
            start, end = int(lo), int(hi)
            if start > end:
                raise ValueError(f"降序 cron 范围不被支持: {part!r}")
            chunk = list(range(start, end + 1))
            if not chunk:
                raise ValueError(f"cron 展开为空: {part!r}")
            for v in chunk:
                if v not in results:
                    results.append(v)
        else:
            v = int(part)
            if v not in results:
                results.append(v)
    if not results:
        raise ValueError(f"cron 字段展开为空: {value!r}")
    return sorted(results)


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
    """Validate Linux cron: numeric five-field with bounds; DOW must be *."""
    fields = _parse_cron_fields(expr)
    bounds = (
        ("minute", fields["minute"], 0, 59),
        ("hour", fields["hour"], 0, 23),
        ("day", fields["day"], 1, 31),
        ("month", fields["month"], 1, 12),
        ("weekday", fields["weekday"], 0, 7),
    )
    for name, field, min_val, max_val in bounds:
        if re.search(r"[A-Za-z@]", field):
            raise ValueError(f"Linux cron 拒绝名称/扩展字段 {name}={field!r}")
        if field != "*":
            values = _parse_cron_field_list(field, max_val)
            for v in values:
                if v < min_val or v > max_val:
                    raise ValueError(
                        f"Linux cron {name} 越界: {v} not in {min_val}..{max_val}"
                    )
    if fields["weekday"] != "*":
        raise ValueError(
            "Linux cron 暂不支持受限 day-of-week（需 DOW=*）；"
            "DOM+DOW 同时限制在 APScheduler→cron 星期翻译验证前被拒绝"
        )
    return expr.strip()


def windows_quote_argument(arg: str) -> str:
    """Windows CreateProcess command-line quoting (MSDN rules)."""
    if not arg:
        return '""'
    if re.search(r'[\s"]', arg) is None:
        return arg
    result: list[str] = ['"']
    num_backslashes = 0
    for ch in arg:
        if ch == "\\":
            num_backslashes += 1
        elif ch == '"':
            result.append("\\" * (num_backslashes * 2 + 1))
            result.append('"')
            num_backslashes = 0
        else:
            if num_backslashes:
                result.append("\\" * num_backslashes)
                num_backslashes = 0
            result.append(ch)
    if num_backslashes:
        result.append("\\" * (num_backslashes * 2))
    result.append('"')
    return "".join(result)


def windows_join_args(args: list[str]) -> str:
    return " ".join(windows_quote_argument(a) for a in args)


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


def current_platform_name() -> Literal["windows", "macos", "linux"]:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    if system == "linux":
        return "linux"
    raise RuntimeError(f"不支持的平台: {system}")


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


def load_smoke_evidence(
    app_root: Optional[Path] = None,
) -> dict[str, bool]:
    """Load smoke evidence; only JSON booleans accepted (not string 'false')."""
    root = Path(app_root) if app_root else Path.cwd()
    path = root / "config" / "system_scheduler_smoke.json"
    if not path.exists():
        return {}
    try:
        import json_utils as json

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: dict[str, bool] = {}
        for k, v in data.items():
            if isinstance(v, bool):
                out[str(k).lower()] = v
        return out
    except Exception:
        return {}


def _smoke_allows(
    evidence: dict[str, bool],
    plat: str,
    scope: SystemTaskScope,
    trig: str,
) -> bool:
    """Platform+scope+trigger specific only; SYSTEM needs elevated proof keys."""
    cell_key = f"{plat}:{scope.value}:{trig}"
    if cell_key not in evidence or not evidence[cell_key]:
        return False
    if scope == SystemTaskScope.SYSTEM:
        combined = f"{plat}:system:elevated_post_restart"
        if evidence.get(combined) is True:
            return True
        elev = f"{plat}:system:elevated"
        restart = f"{plat}:system:post_user_restart"
        return evidence.get(elev) is True and evidence.get(restart) is True
    return True


def build_capabilities(
    platform_name: str,
    *,
    host_platform: Optional[str] = None,
    system_scope_verified: bool = False,
    app_root: Optional[Path] = None,
    smoke_evidence: Optional[dict[str, bool]] = None,
) -> SystemCapabilitiesResponse:
    """Capability matrix: verified/enabled require explicit smoke evidence."""
    host_raw = host_platform or current_platform_name()
    if host_raw not in ("windows", "macos", "linux"):
        host_raw = current_platform_name()
    host: Literal["windows", "macos", "linux"] = cast(
        Literal["windows", "macos", "linux"], host_raw
    )
    cells: list[CapabilityCell] = []
    warnings: list[str] = []
    evidence = (
        smoke_evidence if smoke_evidence is not None else load_smoke_evidence(app_root)
    )

    implemented = {
        ("windows", "date"): True,
        ("windows", "interval"): True,
        ("windows", "cron"): True,
        ("macos", "date"): False,
        ("macos", "interval"): True,
        ("macos", "cron"): True,
        ("linux", "date"): False,
        ("linux", "interval"): False,
        ("linux", "cron"): True,
    }

    for plat in ("windows", "macos", "linux"):
        for scope in (SystemTaskScope.USER, SystemTaskScope.SYSTEM):
            for trig in ("date", "interval", "cron"):
                impl = implemented.get((plat, trig), False)
                smoke_ok = _smoke_allows(evidence, plat, scope, trig)
                if (
                    scope == SystemTaskScope.SYSTEM
                    and system_scope_verified
                    and plat == host
                ):
                    smoke_ok = True
                verified = bool(impl and plat == host and smoke_ok)
                enabled = bool(impl and verified and plat == host)
                reason = ""
                cell_warnings: list[str] = []
                if not impl:
                    reason = "not implemented / rejected by contract"
                elif plat != host:
                    reason = f"disabled on host platform {host}"
                elif not smoke_ok:
                    reason = "implemented but no native smoke evidence"
                else:
                    reason = "enabled"
                if plat == "macos" and trig == "interval" and impl:
                    cell_warnings.append(
                        "StartInterval may miss firings during sleep/overlap"
                    )
                if scope == SystemTaskScope.SYSTEM:
                    cell_warnings.append("system/root scope requires privilege")
                    if not smoke_ok:
                        reason = (
                            "system scope disabled until elevated native smoke verified"
                        )
                cells.append(
                    CapabilityCell(
                        platform=plat,  # type: ignore[arg-type]
                        scope=scope,
                        trigger_type=trig,  # type: ignore[arg-type]
                        implemented=impl,
                        verified=verified,
                        enabled=enabled,
                        reason=reason,
                        warnings=cell_warnings,
                    )
                )

    system_scope_enabled = any(
        c.enabled and c.scope == SystemTaskScope.SYSTEM and c.platform == host
        for c in cells
    )
    if not system_scope_enabled:
        warnings.append("system scope is disabled unless verified")
    if not evidence and not system_scope_verified:
        warnings.append(
            "no smoke evidence (config/system_scheduler_smoke.json); all cells disabled"
        )
    return SystemCapabilitiesResponse(
        platform=host,  # type: ignore[arg-type]
        cells=cells,
        system_scope_enabled=system_scope_enabled,
        warnings=warnings,
    )


def is_capability_enabled(
    caps: SystemCapabilitiesResponse,
    scope: SystemTaskScope,
    trigger_type: str,
) -> tuple[bool, str, list[str]]:
    for cell in caps.cells:
        if (
            cell.platform == caps.platform
            and cell.scope == scope
            and cell.trigger_type == trigger_type
        ):
            return cell.enabled, cell.reason, list(cell.warnings)
    return False, "capability cell not found", []


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
    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        """Backend-specific verification after create. Returns (ok, detail)."""

    @abstractmethod
    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        """查询 OS 报告的下次运行时间"""

    @abstractmethod
    async def list_registered(self) -> list[str]:
        """列出所有 MWU 注册的系统任务 ID"""

    def build_identifier(self, task_id: str, scope: SystemTaskScope) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Windows 后端
# ---------------------------------------------------------------------------


class WindowsBackend(SystemSchedulerBackend):
    """Windows Task Scheduler 后端，使用 schtasks /create /xml 方式注册。"""

    platform_name = "windows"

    def build_identifier(self, task_id: str, scope: SystemTaskScope) -> str:
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

            task_path = self.build_identifier(spec.task_id, spec.scope)

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
        validate_task_id(task_id)
        task_path = self.build_identifier(task_id, scope)

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
                if (
                    "ERROR: The system cannot find the file specified" not in stderr
                    and "does not exist" not in stderr.lower()
                ):
                    logger.warning("schtasks 卸载异常: %s", stderr.strip())
        else:
            await self._run_as_admin(f'/delete /tn "{task_path}" /f', check=False)

    async def is_registered(self, task_id: str, scope: SystemTaskScope) -> bool:
        validate_task_id(task_id)
        task_path = self.build_identifier(task_id, scope)
        proc = await asyncio.to_thread(
            subprocess.run,
            ["schtasks", "/query", "/tn", task_path, "/fo", "list"],
            capture_output=True,
        )
        return proc.returncode == 0

    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        """Export task XML and compare command/args/cwd/trigger/principal/settings."""
        task_path = self.build_identifier(spec.task_id, spec.scope)
        proc = await asyncio.to_thread(
            subprocess.run,
            ["schtasks", "/query", "/tn", task_path, "/xml"],
            capture_output=True,
        )
        if proc.returncode != 0:
            return False, "schtasks query/xml failed"
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

    def _find_desc(self, root: ET.Element, name: str) -> Optional[ET.Element]:
        for el in root.iter():
            if self._local_tag(el.tag) == name:
                return el
        return None

    def _find_settings_child(self, root: ET.Element, name: str) -> Optional[ET.Element]:
        """Find element under Settings subtree only — avoids trigger-scoped collisions."""
        for el in root.iter():
            if self._local_tag(el.tag) != "Settings":
                continue
            for child in el:
                if self._local_tag(child.tag) == name:
                    return child
        return None

    def _find_by_xpath(self, root: ET.Element, path: str) -> Optional[ET.Element]:
        """Simple tag-only path, e.g. 'Settings/Enabled'."""
        parts = path.split("/")
        cur = root
        for p in parts:
            found = None
            for child in cur:
                if self._local_tag(child.tag) == p:
                    found = child
                    break
            if found is None:
                return None
            cur = found
        return cur

    def _compare_exported_xml(
        self, raw: bytes, spec: SystemTaskSpec
    ) -> tuple[bool, str]:
        root = self._decode_task_xml(raw)
        logon = self._find_desc(root, "LogonType")
        user_id = self._find_desc(root, "UserId")
        if spec.scope == SystemTaskScope.SYSTEM:
            if logon is None or (logon.text or "") != "Password":
                return False, (
                    f"SYSTEM LogonType expected Password, got "
                    f"{getattr(logon, 'text', None)}"
                )
            if user_id is None or (user_id.text or "") != "S-1-5-18":
                return False, "SYSTEM UserId expected S-1-5-18"
            if logon is not None and logon.text == "ServiceAccount":
                return False, "invalid ServiceAccount principal"
        else:
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

        # Settings-scoped checks (use subtree lookups to avoid trigger collisions)
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

        def _sb(el_root: ET.Element) -> Optional[str]:
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
                dt = datetime.fromisoformat(got_sb.replace("Z", "+00:00"))
            except Exception:
                return False, f"cron StartBoundary unparseable: {got_sb!r}"
            if dt.minute != minute or dt.hour != hour or dt.second != 0:
                return False, (
                    f"cron StartBoundary time mismatch: "
                    f"{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} "
                    f"!= {hour:02d}:{minute:02d}:00"
                )
            # CalendarTrigger Enabled
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

    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        # Locale-dependent schtasks /v is fragile; do not treat as authoritative.
        validate_task_id(task_id)
        return None

    async def list_registered(self) -> list[str]:
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

    @staticmethod
    def _run_schtasks(
        args: list[str], check: bool = True
    ) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, check=check)

    async def _run_as_admin(self, schtasks_args: str, check: bool = True) -> None:
        import ctypes

        if ctypes.windll.shell32.IsUserAnAdmin():
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

        ret = await asyncio.to_thread(
            ctypes.windll.shell32.ShellExecuteW,
            None,
            "runas",
            "schtasks",
            schtasks_args,
            None,
            1,
        )
        if ret <= 32:
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
        """Build schema-valid Task Scheduler XML."""
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
        if spec.scope == SystemTaskScope.SYSTEM:
            # Schema-valid SYSTEM principal (NOT ServiceAccount)
            uid = ET.SubElement(principal, "UserId")
            uid.text = "S-1-5-18"
            lt = ET.SubElement(principal, "LogonType")
            lt.text = "Password"
            rl = ET.SubElement(principal, "RunLevel")
            rl.text = "HighestAvailable"
        else:
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
            # ISO 8601 duration — whole minutes
            if mins % (24 * 60) == 0 and mins >= 24 * 60:
                days = mins // (24 * 60)
                interval.text = f"P{days}D"
            elif mins % 60 == 0:
                hours = mins // 60
                interval.text = f"PT{hours}H"
            else:
                interval.text = f"PT{mins}M"
            # No end date — indefinite via StopAtDurationEnd false
            stop = ET.SubElement(rep, "StopAtDurationEnd")
            stop.text = "false"
            return

        # cron: only fixed daily M H * * *
        if not trigger_spec.cron_expression:
            raise ValueError("cron 类型的触发器缺少 cron_expression")
        minute, hour = parse_fixed_daily_cron(trigger_spec.cron_expression)

        trigger = ET.SubElement(parent, "CalendarTrigger")
        # StartBoundary sets first activation time-of-day context
        now = datetime.now().astimezone()
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start <= now:
            from datetime import timedelta

            start = start + timedelta(days=1)
        sb = ET.SubElement(trigger, "StartBoundary")
        sb.text = start.isoformat(timespec="seconds")
        enabled = ET.SubElement(trigger, "Enabled")
        enabled.text = "true"
        schedule_by_day = ET.SubElement(trigger, "ScheduleByDay")
        days_interval = ET.SubElement(schedule_by_day, "DaysInterval")
        days_interval.text = "1"
        # Exact daily at M:H — NO one-minute repetition


# ---------------------------------------------------------------------------
# macOS 后端
# ---------------------------------------------------------------------------


class MacOSBackend(SystemSchedulerBackend):
    """macOS 14+ launchd 后端，使用 launchctl bootstrap / bootout。"""

    platform_name = "macos"

    def build_identifier(self, task_id: str, scope: SystemTaskScope) -> str:
        return self._plist_label(task_id, scope)

    @staticmethod
    def _plist_label(task_id: str, scope: SystemTaskScope) -> str:
        if scope == SystemTaskScope.SYSTEM:
            return f"com.mwu.daemon.{task_id}"
        return f"com.mwu.task.{task_id}"

    @staticmethod
    def _plist_path(task_id: str, scope: SystemTaskScope) -> Path:
        label = MacOSBackend._plist_label(task_id, scope)
        if scope == SystemTaskScope.SYSTEM:
            return Path(f"/Library/LaunchDaemons/{label}.plist")
        return Path(f"~/Library/LaunchAgents/{label}.plist").expanduser()

    def _domain(self, scope: SystemTaskScope) -> str:
        if scope == SystemTaskScope.SYSTEM:
            return "system"
        return f"gui/{_get_uid()}"

    async def register(self, spec: SystemTaskSpec) -> None:
        validate_task_id(spec.task_id)
        validate_trigger_for_platform(self.platform_name, spec.trigger)
        label = self._plist_label(spec.task_id, spec.scope)
        plist_path = self._plist_path(spec.task_id, spec.scope)
        plist_data = self._build_plist(spec)

        if spec.scope == SystemTaskScope.USER:
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._write_plist, plist_path, plist_data)
            await self._bootstrap_idempotent(label, str(plist_path), spec.scope)
        else:
            plist_xml = await asyncio.to_thread(plistlib.dumps, plist_data)
            plist_xml_str = plist_xml.decode("utf-8")
            await self._run_osascript_admin(
                self._admin_register_script(str(plist_path), label, plist_xml_str)
            )
        logger.info(
            "macOS launchd 任务注册成功: %s (scope=%s)", label, spec.scope.value
        )

    async def unregister(self, task_id: str, scope: SystemTaskScope) -> None:
        validate_task_id(task_id)
        label = self._plist_label(task_id, scope)
        plist_path = self._plist_path(task_id, scope)

        if scope == SystemTaskScope.USER:
            domain = f"gui/{_get_uid()}"
            proc = await asyncio.to_thread(
                subprocess.run,
                ["launchctl", "bootout", f"{domain}/{label}"],
                capture_output=True,
            )
            if proc.returncode != 0:
                stderr = cast(bytes, proc.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                if "Could not find" not in stderr and "No such process" not in stderr:
                    logger.debug("launchctl bootout: %s", stderr.strip())
            if await asyncio.to_thread(os.path.exists, str(plist_path)):
                await asyncio.to_thread(os.unlink, str(plist_path))
        else:
            await self._run_osascript_admin(
                self._admin_unregister_script(str(plist_path), label)
            )

    async def is_registered(self, task_id: str, scope: SystemTaskScope) -> bool:
        validate_task_id(task_id)
        label = self._plist_label(task_id, scope)
        domain = self._domain(scope)
        # Exact domain/label via launchctl print
        proc = await asyncio.to_thread(
            subprocess.run,
            ["launchctl", "print", f"{domain}/{label}"],
            capture_output=True,
        )
        return proc.returncode == 0

    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        label = self._plist_label(spec.task_id, spec.scope)
        plist_path = self._plist_path(spec.task_id, spec.scope)
        domain = self._domain(spec.scope)

        if not await asyncio.to_thread(os.path.exists, str(plist_path)):
            return False, "plist missing"
        try:
            mode = await asyncio.to_thread(os.stat, str(plist_path))
            # expect 0600 or 0400
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
            subprocess.run,
            ["launchctl", "print", f"{domain}/{label}"],
            capture_output=True,
        )
        if proc.returncode != 0:
            return False, f"launchctl print {domain}/{label} failed"
        return True, f"verified {domain}/{label}"

    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        return None

    async def list_registered(self) -> list[str]:
        result: list[str] = []
        pattern = re.compile(r"com\.mwu\.(?:task|daemon)\.([a-f0-9-]{36})\.plist$")

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

    @staticmethod
    def _write_plist(path: Path, data: dict) -> None:
        with open(path, "wb") as f:
            plistlib.dump(data, f)
        # Explicit chmod 0600
        os.chmod(path, 0o600)

    async def _bootstrap_idempotent(
        self, label: str, plist_path_str: str, scope: SystemTaskScope
    ) -> None:
        domain = self._domain(scope)
        target = f"{domain}/{label}"

        # Modern idempotent lifecycle: bootout then bootstrap
        await asyncio.to_thread(
            subprocess.run,
            ["launchctl", "bootout", target],
            capture_output=True,
        )
        proc = await asyncio.to_thread(
            subprocess.run,
            ["launchctl", "bootstrap", domain, plist_path_str],
            capture_output=True,
        )
        if proc.returncode != 0:
            stderr = cast(bytes, proc.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(f"launchctl bootstrap 失败: {stderr.strip()}")

    def _build_plist(self, spec: SystemTaskSpec) -> dict:
        label = self._plist_label(spec.task_id, spec.scope)
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
            # No Year key
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

    async def _run_osascript_admin(self, script: str) -> None:
        # argv form: raw shell never embedded inside a double-quoted AppleScript literal
        apple_script = (
            "on run argv\n"
            "  do shell script (item 1 of argv) with administrator privileges\n"
            "end run"
        )
        proc = await asyncio.to_thread(
            subprocess.run,
            ["osascript", "-e", apple_script, script],
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
        # Base64 payload avoids AppleScript/shell quoting breakage
        import base64

        b64 = base64.b64encode(plist_xml.encode("utf-8")).decode("ascii")
        path_b64 = base64.b64encode(plist_path.encode("utf-8")).decode("ascii")
        script = (
            f"PLIST_PATH=$(printf %s {path_b64} | base64 -D 2>/dev/null || "
            f"printf %s {path_b64} | base64 -d); "
            f"mkdir -p /Library/LaunchDaemons && "
            f"printf %s {b64} | (base64 -D 2>/dev/null || base64 -d) "
            f'> "$PLIST_PATH" && '
            f'chmod 600 "$PLIST_PATH" && '
            f"launchctl bootout system/{label} 2>/dev/null; "
            f'launchctl bootstrap system "$PLIST_PATH"'
        )
        return script

    def _admin_unregister_script(self, plist_path: str, label: str) -> str:
        import base64

        path_b64 = base64.b64encode(plist_path.encode("utf-8")).decode("ascii")
        script = (
            f"PLIST_PATH=$(printf %s {path_b64} | base64 -D 2>/dev/null || "
            f"printf %s {path_b64} | base64 -d); "
            f"launchctl bootout system/{label} 2>/dev/null; "
            f'rm -f "$PLIST_PATH"'
        )
        return script


# ---------------------------------------------------------------------------
# Linux 后端
# ---------------------------------------------------------------------------


class LinuxBackend(SystemSchedulerBackend):
    """Linux crontab 后端。"""

    platform_name = "linux"
    _MWU_MARKER_RE = re.compile(r"^#\s*MWU:([a-f0-9-]{36})\s*$")
    _CRONTAB_LOCK_NAME = "mwu-crontab.lock"

    def build_identifier(self, task_id: str, scope: SystemTaskScope) -> str:
        if scope == SystemTaskScope.SYSTEM:
            return f"/etc/cron.d/mwu-{task_id}"
        return f"mwu-{task_id}"

    async def register(self, spec: SystemTaskSpec) -> None:
        validate_task_id(spec.task_id)
        validate_trigger_for_platform(self.platform_name, spec.trigger)

        if spec.scope == SystemTaskScope.USER:
            await self._register_user_cron(spec)
        else:
            await self._register_system_cron(spec)
        logger.info("Linux 任务注册成功: %s (scope=%s)", spec.task_id, spec.scope.value)

    async def unregister(self, task_id: str, scope: SystemTaskScope) -> None:
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
                    "not authorized" not in stderr.lower()
                    and "user cancelled" not in stderr.lower()
                ):
                    logger.debug("pkexec rm 失败: %s", stderr.strip())

    async def is_registered(self, task_id: str, scope: SystemTaskScope) -> bool:
        validate_task_id(task_id)
        if scope == SystemTaskScope.USER:
            marker = f"# MWU:{task_id}"
            crontab_text = await self._read_crontab()
            return marker in crontab_text
        file_path = f"/etc/cron.d/mwu-{task_id}"
        return await asyncio.to_thread(os.path.exists, file_path)

    async def verify_registration(self, spec: SystemTaskSpec) -> tuple[bool, str]:
        expected_line = self._build_cron_line(spec)
        marker = f"# MWU:{spec.task_id}"
        if spec.scope == SystemTaskScope.USER:
            text = await self._read_crontab()
            lines = text.splitlines()
            for i, line in enumerate(lines):
                if line.strip() == marker:
                    if i + 1 < len(lines) and lines[i + 1].strip() == expected_line:
                        return True, "user crontab marker+line match"
                    return False, "user crontab line mismatch"
            return False, "user crontab marker missing"
        file_path = f"/etc/cron.d/mwu-{spec.task_id}"
        if not await asyncio.to_thread(os.path.exists, file_path):
            return False, "cron.d file missing"
        try:
            st = await asyncio.to_thread(os.stat, file_path)
            if getattr(st, "st_uid", 0) != 0:
                return False, f"cron.d file not root-owned (uid={st.st_uid})"
            mode = st.st_mode & 0o777
            if mode & 0o022:
                return False, f"cron.d file is group/other writable (mode={oct(mode)})"
            content = await asyncio.to_thread(
                Path(file_path).read_text, encoding="utf-8"
            )
            if expected_line not in content and not any(
                expected_line.split(" root ", 1)[-1] in content for _ in [0]
            ):
                # system line includes user field
                sys_line = self._build_system_cron_line(spec)
                if sys_line not in content:
                    return False, "cron.d content mismatch"
            return True, "cron.d verified"
        except Exception as e:
            return False, f"cron.d verify error: {e}"

    async def get_next_run_time(
        self, task_id: str, scope: SystemTaskScope
    ) -> Optional[datetime]:
        return None

    async def list_registered(self) -> list[str]:
        result: list[str] = []
        crontab_text = await self._read_crontab()
        for line in crontab_text.splitlines():
            m = self._MWU_MARKER_RE.match(line.strip())
            if m:
                tid = m.group(1)
                if tid not in result:
                    result.append(tid)

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

    def _crontab_lock_path(self) -> Path:
        return Path.home() / ".mwu" / self._CRONTAB_LOCK_NAME

    def _acquire_crontab_lock(self):
        from services.process_lock import AdvisoryFileLock

        lock = AdvisoryFileLock(self._crontab_lock_path())
        lock.acquire(timeout_seconds=30.0)
        return lock

    async def _read_crontab(self) -> str:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["crontab", "-l"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = f"{proc.stderr or ''}{proc.stdout or ''}"
            err_l = err.lower()
            if "no crontab for" in err_l or "no crontab" in err_l:
                return ""
            raise RuntimeError(f"crontab -l failed: {err.strip() or proc.returncode}")
        return cast(str, proc.stdout or "")

    async def _write_crontab(self, content: str) -> None:
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
            proc = await asyncio.to_thread(
                subprocess.run,
                ["crontab", "-r"],
                capture_output=True,
            )
            if proc.returncode != 0:
                stderr = cast(bytes, proc.stderr or b"").decode(
                    "utf-8", errors="replace"
                )
                if "no crontab for" not in stderr.lower():
                    logger.debug("crontab -r 失败: %s", stderr.strip())
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
        """Shell-quoted cd + executable + args for /bin/sh -c."""
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

    def _build_system_cron_line(self, spec: SystemTaskSpec) -> str:
        trigger_spec = spec.trigger
        if trigger_spec.trigger_type != "cron" or not trigger_spec.cron_expression:
            raise ValueError("Linux 仅支持 cron 触发器")
        cron_timing = validate_linux_cron_expression(trigger_spec.cron_expression)
        return f"{cron_timing} root {self._build_command_body(spec)}"

    async def _register_system_cron(self, spec: SystemTaskSpec) -> None:
        task_path = f"/etc/cron.d/mwu-{spec.task_id}"
        content = f"# MWU:{spec.task_name}\n{self._build_system_cron_line(spec)}\n"
        await self._write_via_pkexec(task_path, content)

    async def _write_via_pkexec(self, file_path: str, content: str) -> None:
        """Atomic root-owned 0644 write via temp + mv (argv only, no shell)."""
        import tempfile as _tf

        with _tf.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
            tf.write(content)
            local_tmp = tf.name
        remote_tmp = f"{file_path}.mwu.tmp"
        try:
            with open(local_tmp, "r", encoding="utf-8") as src:
                proc = await asyncio.to_thread(
                    subprocess.run,
                    ["pkexec", "tee", remote_tmp],
                    stdin=src,
                    capture_output=True,
                    text=True,
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
            for args in (
                ["pkexec", "chown", "root:root", remote_tmp],
                ["pkexec", "chmod", "644", remote_tmp],
                ["pkexec", "mv", "-f", remote_tmp, file_path],
            ):
                p = await asyncio.to_thread(
                    subprocess.run, args, capture_output=True, text=True
                )
                if p.returncode != 0:
                    stderr = cast(str, p.stderr or "").strip()
                    raise RuntimeError(f"pkexec {' '.join(args[1:])} failed: {stderr}")
        finally:
            try:
                os.unlink(local_tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------


def get_backend(platform_name: Optional[str] = None) -> SystemSchedulerBackend:
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
    app_root: Path, task_id: str, *, frozen: Optional[bool] = None
) -> tuple[str, list[str]]:
    """Build source/frozen native command for OS registration.

    Source mode: python_executable + absolute main.py + --headless --task id
    Frozen mode: executable + --headless --task id
    """
    is_frozen = (
        getattr(__import__("sys"), "frozen", False) if frozen is None else frozen
    )
    import sys

    if is_frozen:
        return sys.executable, ["--headless", "--task", task_id]
    main_py = str((Path(app_root) / "main.py").resolve())
    return sys.executable, [main_py, "--headless", "--task", task_id]
