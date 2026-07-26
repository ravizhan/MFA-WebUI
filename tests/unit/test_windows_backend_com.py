"""Linux-runnable unit tests for WindowsBackend COM + macOS unregister semantics.

Injects fake pythoncom / win32com via monkeypatch — no real Windows required.
"""

from __future__ import annotations

import re
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from services.native_cron import parse_native_cron
from services import system_scheduler_backend as ssb
from services.system_scheduler_backend import (
    LinuxBackend,
    MacOSBackend,
    NativeTaskSpec,
    WindowsBackend,
    _TASK_ACTION_EXEC,
    _TASK_CREATE_OR_UPDATE,
    _TASK_INSTANCES_PARALLEL,
    _TASK_LOGON_INTERACTIVE_TOKEN,
    _TASK_TRIGGER_DAILY,
    _TASK_TRIGGER_MONTHLY,
    _TASK_TRIGGER_TIME,
    _TASK_TRIGGER_WEEKLY,
    _com_is_not_found,
    _next_hourly_start_boundary,
    windows_join_args,
)

_UUID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Fake COM objects
# ---------------------------------------------------------------------------


class FakeComError(Exception):
    def __init__(self, hresult: int, message: str = "not found") -> None:
        self.hresult = hresult
        super().__init__(hresult, message, None, None)


class FakeRepetition:
    def __init__(self) -> None:
        self.Interval: str | None = None
        self.StopAtDurationEnd: bool | None = None


class FakeTrigger:
    def __init__(self, trigger_type: int) -> None:
        self.type = trigger_type
        self.StartBoundary: str | None = None
        self.Enabled: bool | None = None
        self.DaysInterval: int | None = None
        self.DaysOfWeek: int | None = None
        self.WeeksInterval: int | None = None
        self.DaysOfMonth: int | None = None
        self.MonthsOfYear: int | None = None
        self.Repetition = FakeRepetition()


class FakeTriggers:
    def __init__(self) -> None:
        self.created: list[FakeTrigger] = []

    def Create(self, trigger_type: int) -> FakeTrigger:
        t = FakeTrigger(trigger_type)
        self.created.append(t)
        return t


class FakeAction:
    def __init__(self) -> None:
        self.Path: str | None = None
        self.Arguments: str | None = None
        self.WorkingDirectory: str | None = None


class FakeActions:
    def __init__(self) -> None:
        self.created: list[tuple[int, FakeAction]] = []

    def Create(self, action_type: int) -> FakeAction:
        a = FakeAction()
        self.created.append((action_type, a))
        return a


class FakeRegistrationInfo:
    def __init__(self) -> None:
        self.Description: str | None = None


class FakePrincipal:
    def __init__(self) -> None:
        self.LogonType: int | None = None


class FakeSettings:
    def __init__(self) -> None:
        self.Enabled: bool | None = None
        self.StartWhenAvailable: bool | None = None
        self.AllowDemandStart: bool | None = None
        self.ExecutionTimeLimit: str | None = None
        self.MultipleInstances: int | None = None
        self.DisallowStartIfOnBatteries: bool | None = None
        self.StopIfGoingOnBatteries: bool | None = None


class FakeTaskDefinition:
    def __init__(self) -> None:
        self.RegistrationInfo = FakeRegistrationInfo()
        self.Principal = FakePrincipal()
        self.Settings = FakeSettings()
        self.Triggers = FakeTriggers()
        self.Actions = FakeActions()


class FakeRegisteredTask:
    def __init__(self, name: str) -> None:
        self.Name = name


class FakeTaskCollection:
    """1-based COM-style collection."""

    def __init__(self, names: list[str]) -> None:
        self._names = list(names)

    @property
    def Count(self) -> int:
        return len(self._names)

    def Item(self, index: int) -> FakeRegisteredTask:
        if index < 1 or index > len(self._names):
            raise FakeComError(0x80070057, f"bad index {index}")
        return FakeRegisteredTask(self._names[index - 1])


class FakeFolder:
    def __init__(self, path: str, store: dict[str, Any]) -> None:
        self.path = path
        self._store = store
        self.registered: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def RegisterTaskDefinition(
        self,
        name: str,
        task_def: FakeTaskDefinition,
        flags: int,
        user: Any,
        password: Any,
        logon_type: int,
    ) -> None:
        self.registered.append(
            {
                "name": name,
                "task_def": task_def,
                "flags": flags,
                "user": user,
                "password": password,
                "logon_type": logon_type,
            }
        )
        self._store[name] = task_def

    def GetTask(self, name: str) -> FakeRegisteredTask:
        if name not in self._store:
            raise FakeComError(0x80070002, f"task not found: {name}")
        return FakeRegisteredTask(name)

    def DeleteTask(self, name: str, flags: int) -> None:
        if name not in self._store:
            raise FakeComError(0x80070002, f"task not found: {name}")
        del self._store[name]
        self.deleted.append(name)

    def GetTasks(self, flags: int) -> FakeTaskCollection:
        return FakeTaskCollection(list(self._store.keys()))


class FakeRootFolder:
    def __init__(self, service: FakeScheduleService) -> None:
        self._service = service

    def CreateFolder(self, name: str) -> FakeFolder:
        if name != "MWU":
            raise FakeComError(0x80070057, f"unexpected folder {name}")
        folder = FakeFolder("\\MWU", self._service.tasks)
        self._service.folders["\\MWU"] = folder
        self._service.created_folders.append(name)
        return folder


class FakeScheduleService:
    def __init__(self, *, folder_exists: bool = True) -> None:
        self.tasks: dict[str, Any] = {}
        self.folders: dict[str, FakeFolder] = {}
        self.created_folders: list[str] = []
        self.connected = False
        self.new_tasks: list[FakeTaskDefinition] = []
        if folder_exists:
            self.folders["\\MWU"] = FakeFolder("\\MWU", self.tasks)

    def Connect(self) -> None:
        self.connected = True

    def GetFolder(self, path: str) -> FakeFolder | FakeRootFolder:
        if path == "\\":
            return FakeRootFolder(self)
        if path not in self.folders:
            raise FakeComError(0x80070003, f"folder not found: {path}")
        return self.folders[path]

    def NewTask(self, flags: int) -> FakeTaskDefinition:
        assert flags == 0
        td = FakeTaskDefinition()
        self.new_tasks.append(td)
        return td


class FakePythoncom:
    def __init__(self) -> None:
        self.init_count = 0
        self.uninit_count = 0

    def CoInitialize(self) -> None:
        self.init_count += 1

    def CoUninitialize(self) -> None:
        self.uninit_count += 1


def _install_fake_com(
    monkeypatch: pytest.MonkeyPatch,
    service: FakeScheduleService,
    pythoncom: FakePythoncom | None = None,
) -> FakePythoncom:
    """Inject fake pythoncom + win32com.client into sys.modules."""
    pc = pythoncom or FakePythoncom()

    win32com_mod = types.ModuleType("win32com")
    client_mod = types.ModuleType("win32com.client")

    def dispatch(prog_id: str) -> FakeScheduleService:
        assert prog_id == "Schedule.Service"
        return service

    setattr(client_mod, "Dispatch", dispatch)
    setattr(win32com_mod, "client", client_mod)

    monkeypatch.setitem(sys.modules, "pythoncom", pc)
    monkeypatch.setitem(sys.modules, "win32com", win32com_mod)
    monkeypatch.setitem(sys.modules, "win32com.client", client_mod)
    return pc


def _spec(
    *,
    cron: str = "0 9 * * *",
    task_id: str = _UUID,
    task_name: str = "demo",
    exe_path: str = r"C:\MWU\MWU.exe",
    cli_args: list[str] | None = None,
    working_dir: str = r"C:\MWU",
) -> NativeTaskSpec:
    return NativeTaskSpec(
        task_id=task_id,
        task_name=task_name,
        exe_path=exe_path,
        cli_args=cli_args if cli_args is not None else ["--scheduled-task", task_id],
        cron=parse_native_cron(cron),
        working_dir=working_dir,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_module_imports_without_pywin32(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the backend module must not require pywin32 on any platform."""
    # A None entry makes imports fail even when pywin32 is installed on Windows CI.
    monkeypatch.setitem(sys.modules, "pythoncom", None)
    monkeypatch.setitem(sys.modules, "win32com", None)
    monkeypatch.setitem(sys.modules, "win32com.client", None)

    # Re-import path already loaded; assert WindowsBackend._import_com fails cleanly
    # and module-level symbols remain available.
    import services.system_scheduler_backend as mod

    assert hasattr(mod, "WindowsBackend")
    assert hasattr(mod, "LinuxBackend")
    assert hasattr(mod, "MacOSBackend")
    abstract = getattr(mod.SystemSchedulerBackend, "__abstractmethods__", set())
    assert "verify_registration" not in abstract

    backend = mod.WindowsBackend()
    with pytest.raises(RuntimeError, match="pywin32"):
        backend._import_com()


def test_register_maps_daily_task_definition(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeScheduleService(folder_exists=True)
    pc = _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()
    spec = _spec(cron="30 8 * * *", task_name="morning")

    backend.register(spec)

    assert pc.init_count == 1
    assert pc.uninit_count == 1
    assert service.connected is True
    assert len(service.folders["\\MWU"].registered) == 1
    rec = service.folders["\\MWU"].registered[0]
    assert rec["name"] == _UUID
    assert rec["flags"] == _TASK_CREATE_OR_UPDATE
    assert rec["logon_type"] == _TASK_LOGON_INTERACTIVE_TOKEN

    td: FakeTaskDefinition = rec["task_def"]
    assert td.RegistrationInfo.Description == "MWU Scheduled Task: morning"
    assert td.Principal.LogonType == _TASK_LOGON_INTERACTIVE_TOKEN
    assert td.Settings.Enabled is True
    assert td.Settings.StartWhenAvailable is True
    assert td.Settings.AllowDemandStart is True
    assert td.Settings.ExecutionTimeLimit == "PT2H"
    assert td.Settings.MultipleInstances == _TASK_INSTANCES_PARALLEL
    assert td.Settings.DisallowStartIfOnBatteries is False
    assert td.Settings.StopIfGoingOnBatteries is False

    assert len(td.Triggers.created) == 1
    trigger = td.Triggers.created[0]
    assert trigger.type == _TASK_TRIGGER_DAILY
    assert trigger.Enabled is True
    assert trigger.DaysInterval == 1
    assert trigger.StartBoundary is not None
    assert (
        trigger.StartBoundary.endswith("08:30:00")
        or "T08:30:00" in trigger.StartBoundary
    )

    assert len(td.Actions.created) == 1
    action_type, action = td.Actions.created[0]
    assert action_type == _TASK_ACTION_EXEC
    assert action.Path == r"C:\MWU\MWU.exe"
    assert action.Arguments == windows_join_args(["--scheduled-task", _UUID])
    assert action.WorkingDirectory == r"C:\MWU"


def test_register_hourly_weekly_monthly_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = WindowsBackend()

    # HOURLY — boundary after call time and within ~1 hour (not next calendar day)
    service = FakeScheduleService()
    _install_fake_com(monkeypatch, service)
    # naive 本地墙钟：StartBoundary 修复后为 naive，比较必须 naive vs naive
    before = datetime.now()
    backend.register(_spec(cron="45 * * * *"))
    t = service.folders["\\MWU"].registered[-1]["task_def"].Triggers.created[0]
    assert t.type == _TASK_TRIGGER_TIME
    assert t.Repetition.Interval == "PT1H"
    assert t.Repetition.StopAtDurationEnd is False
    assert t.StartBoundary is not None
    boundary = datetime.fromisoformat(t.StartBoundary)
    assert boundary > before
    assert boundary - before <= timedelta(hours=1, seconds=5)
    assert boundary.minute == 45
    assert boundary.second == 0
    # Must not be deferred a full day past the call window
    assert boundary.date() in {before.date(), (before + timedelta(days=1)).date()}
    if boundary.date() > before.date():
        # only valid near midnight when next :45 rolls past midnight
        assert before.hour == 23 or before.minute >= 45

    # WEEKLY Monday
    service = FakeScheduleService()
    _install_fake_com(monkeypatch, service)
    backend.register(_spec(cron="0 9 * * 1"))
    t = service.folders["\\MWU"].registered[-1]["task_def"].Triggers.created[0]
    assert t.type == _TASK_TRIGGER_WEEKLY
    assert t.DaysOfWeek == 0x02  # MON
    assert t.WeeksInterval == 1

    # MONTHLY day 15 all months
    service = FakeScheduleService()
    _install_fake_com(monkeypatch, service)
    backend.register(_spec(cron="0 0 15 * *"))
    t = service.folders["\\MWU"].registered[-1]["task_def"].Triggers.created[0]
    assert t.type == _TASK_TRIGGER_MONTHLY
    assert t.DaysOfMonth == 1 << (15 - 1)
    assert t.MonthsOfYear == 0xFFF

    # MONTHLY January only
    service = FakeScheduleService()
    _install_fake_com(monkeypatch, service)
    backend.register(_spec(cron="0 0 1 1 *"))
    t = service.folders["\\MWU"].registered[-1]["task_def"].Triggers.created[0]
    assert t.type == _TASK_TRIGGER_MONTHLY
    assert t.DaysOfMonth == 1 << 0
    assert t.MonthsOfYear == 0x001  # JAN


def test_next_hourly_start_boundary_same_hour() -> None:
    # 新契约：naive 本地墙钟入 → naive 本地墙钟出（isoformat 不带 offset）。
    now = datetime(2026, 7, 20, 10, 30, 15)
    result = _next_hourly_start_boundary(45, now=now)
    assert result == datetime(2026, 7, 20, 10, 45, 0)


def test_next_hourly_start_boundary_next_hour() -> None:
    now = datetime(2026, 7, 20, 10, 50, 0)
    result = _next_hourly_start_boundary(45, now=now)
    assert result == datetime(2026, 7, 20, 11, 45, 0)


def test_next_hourly_start_boundary_aware_now_normalized_to_naive() -> None:
    # 新契约：注入 aware `now` 时归一为 naive 本地墙钟（剥离 tzinfo），
    # 否则 isoformat() 会带上 +HH:MM 偏移 → Task Scheduler 2.0 视为
    # “跨时区同步”语义，DST 切换后逐次漂移 1 小时。
    # 仅断言 tzinfo 与滚到 :45 的确定性属性，不锁定具体时刻（依赖系统本地时区）。
    tz = timezone(timedelta(hours=8))
    now = datetime(2026, 7, 20, 10, 50, 0, tzinfo=tz)
    result = _next_hourly_start_boundary(45, now=now)
    assert result.tzinfo is None
    assert result.minute == 45
    assert result.second == 0


def test_start_boundary_has_no_utc_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：StartBoundary 必须是 naive 本地墙钟（无 +HH:MM / Z）。

    带 offset 的 StartBoundary 会被 Task Scheduler 2.0 当作“跨时区同步”语义，
    把触发时刻钉死于绝对瞬时，DST 每次切换后日/周/月触发都会漂移 1 小时。
    覆盖日/周/月/时四种触发器。
    """
    naive_iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    backend = WindowsBackend()

    cases = [
        ("30 8 * * *", _TASK_TRIGGER_DAILY),
        ("45 * * * *", _TASK_TRIGGER_TIME),  # HOURLY
        ("0 9 * * 1", _TASK_TRIGGER_WEEKLY),
        ("0 0 15 * *", _TASK_TRIGGER_MONTHLY),
    ]
    for cron, trigger_type in cases:
        service = FakeScheduleService()
        _install_fake_com(monkeypatch, service)
        backend.register(_spec(cron=cron))
        trig = service.folders["\\MWU"].registered[-1]["task_def"].Triggers.created[0]
        assert trig.type == trigger_type, cron
        assert trig.StartBoundary is not None, cron
        assert naive_iso.match(trig.StartBoundary), (
            f"{cron}: StartBoundary 必须为 naive 本地墙钟，实际为 {trig.StartBoundary!r}"
        )


def test_register_creates_mwu_folder_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = FakeScheduleService(folder_exists=False)
    _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()
    backend.register(_spec())
    assert "MWU" in service.created_folders
    assert "\\MWU" in service.folders
    assert len(service.folders["\\MWU"].registered) == 1


def test_list_missing_folder_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeScheduleService(folder_exists=False)
    pc = _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()
    assert backend.list_registered_task_ids() == []
    assert pc.init_count == 1
    assert pc.uninit_count == 1


def test_unregister_deletes_task(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeScheduleService()
    service.tasks[_UUID] = object()
    _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()

    backend.unregister(_UUID)
    assert _UUID not in service.tasks


def test_unregister_missing_task_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """任务已被外部删除时，unregister 应幂等成功而非阻塞 disable/pause/delete 流程。"""
    service = FakeScheduleService()
    _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()
    # 不应抛异常；_com_is_not_found 判定为「任务不存在」时视为已注销
    backend.unregister(_UUID)
    assert _UUID not in service.tasks


def test_unregister_missing_folder_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeScheduleService(folder_exists=False)
    _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()
    with pytest.raises(RuntimeError, match="GetFolder"):
        backend.unregister(_UUID)


def test_get_task_error_becomes_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeScheduleService()

    class BoomFolder(FakeFolder):
        def DeleteTask(self, name: str, flags: int) -> None:
            raise FakeComError(0x80070005, "access denied")

    service.folders["\\MWU"] = BoomFolder("\\MWU", service.tasks)
    _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()
    with pytest.raises(RuntimeError, match="删除失败"):
        backend.unregister(_UUID)


def test_task_not_ready_hresult_is_not_missing() -> None:
    """0x8004130A is SCHED_E_TASK_NOT_READY, not not-found."""
    exc = FakeComError(0x8004130A, "The task is not ready to run")
    assert _com_is_not_found(exc) is False
    assert _com_is_not_found(FakeComError(0x80070002, "file not found")) is True


def test_com_is_not_found_reads_nested_excepinfo_scode() -> None:
    """DISP_E_EXCEPTION outer + nested 0x80070002 (real Win32 \\MWU missing shape)."""
    # Real pywintypes.com_error:
    # args=(-2147352567, '发生意外。', (0,None,None,None,0,-2147024894), None)
    # outer 0x80020009, nested scode -2147024894 == 0x80070002
    outer = -2147352567  # 0x80020009 DISP_E_EXCEPTION
    nested_scode = -2147024894  # 0x80070002 ERROR_FILE_NOT_FOUND
    excepinfo = (0, None, None, None, 0, nested_scode)

    class WrappedComError(Exception):
        def __init__(self) -> None:
            self.hresult = outer
            self.excepinfo = excepinfo
            super().__init__(outer, "发生意外。", excepinfo, None)

    assert _com_is_not_found(WrappedComError()) is True

    # args[2] only (no excepinfo attribute) must also work
    class ArgsOnlyComError(Exception):
        def __init__(self) -> None:
            self.hresult = outer
            super().__init__(outer, "发生意外。", excepinfo, None)

    assert _com_is_not_found(ArgsOnlyComError()) is True

    # Chinese outer message alone must not classify as not-found without nested code
    class ChineseOnlyError(Exception):
        def __init__(self) -> None:
            self.hresult = outer
            super().__init__(outer, "发生意外。", None, None)

    assert _com_is_not_found(ChineseOnlyError()) is False


def test_list_missing_folder_wrapped_disp_exception_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing \\MWU as DISP_E_EXCEPTION + nested FILE_NOT_FOUND → []."""
    outer = -2147352567
    nested_scode = -2147024894
    excepinfo = (0, None, None, None, 0, nested_scode)

    class WrappedComError(Exception):
        def __init__(self) -> None:
            self.hresult = outer
            self.excepinfo = excepinfo
            super().__init__(outer, "发生意外。", excepinfo, None)

    service = FakeScheduleService(folder_exists=False)

    def boom_get_folder(path: str) -> FakeFolder | FakeRootFolder:
        if path == "\\":
            return FakeRootFolder(service)
        raise WrappedComError()

    monkeypatch.setattr(service, "GetFolder", boom_get_folder)
    pc = _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()

    assert backend.list_registered_task_ids() == []
    assert pc.init_count == 1
    assert pc.uninit_count == 1


def test_get_task_not_ready_raises_not_false(monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeScheduleService()

    class NotReadyFolder(FakeFolder):
        def DeleteTask(self, name: str, flags: int) -> None:
            raise FakeComError(0x8004130A, "The task is not ready to run")

    service.folders["\\MWU"] = NotReadyFolder("\\MWU", service.tasks)
    _install_fake_com(monkeypatch, service)
    backend = WindowsBackend()
    with pytest.raises(RuntimeError, match="删除失败"):
        backend.unregister(_UUID)


def test_build_identifier() -> None:
    backend = WindowsBackend()
    assert backend.build_identifier(_UUID) == f"\\MWU\\{_UUID}"


# ---------------------------------------------------------------------------
# macOS unregister (bootout + plist) semantics
# ---------------------------------------------------------------------------


def _cp(
    returncode: int = 0, stderr: str = "", stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["launchctl"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_macos_unregister_bootout_ok_deletes_plist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = MacOSBackend()
    plist = tmp_path / f"com.mwu.task.{_UUID}.plist"
    plist.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(backend, "_plist_path", lambda task_id: plist)
    monkeypatch.setattr(ssb, "_run_text", lambda args, check=False: _cp(0))

    backend.unregister(_UUID)
    assert not plist.exists()


def test_macos_unregister_not_found_with_plist_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = MacOSBackend()
    plist = tmp_path / f"com.mwu.task.{_UUID}.plist"
    plist.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(backend, "_plist_path", lambda task_id: plist)
    monkeypatch.setattr(
        ssb,
        "_run_text",
        lambda args, check=False: _cp(113, stderr="Could not find service"),
    )

    backend.unregister(_UUID)
    assert not plist.exists()


def test_macos_unregister_not_found_without_plist_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """任务已被外部删除（既未加载也无残留 plist）时，unregister 幂等成功
    而非阻塞 disable/pause/delete 流程。与 WindowsBackend 行为一致。"""
    backend = MacOSBackend()
    plist = tmp_path / f"com.mwu.task.{_UUID}.plist"
    assert not plist.exists()
    monkeypatch.setattr(backend, "_plist_path", lambda task_id: plist)
    monkeypatch.setattr(
        ssb,
        "_run_text",
        lambda args, check=False: _cp(1, stderr="Could not find service"),
    )

    # 不应抛异常：ABC 契约 —— 任务已通过外部途径被删除，视为已注销
    backend.unregister(_UUID)
    assert not plist.exists()


def test_macos_unregister_other_bootout_error_keeps_plist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backend = MacOSBackend()
    plist = tmp_path / f"com.mwu.task.{_UUID}.plist"
    plist.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(backend, "_plist_path", lambda task_id: plist)
    monkeypatch.setattr(
        ssb,
        "_run_text",
        lambda args, check=False: _cp(1, stderr="permission denied"),
    )

    with pytest.raises(RuntimeError, match="bootout failed"):
        backend.unregister(_UUID)
    assert plist.exists()


# ---------------------------------------------------------------------------
# Linux unregister (crontab -l/-/-r) semantics
# ---------------------------------------------------------------------------


def test_linux_unregister_empty_crontab_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 crontab 时，unregister 幂等成功而非阻塞 disable/pause/delete 流程。
    与 WindowsBackend / MacOSBackend 行为一致。"""
    backend = LinuxBackend()
    calls: list[list[str]] = []

    def fake_run_text(args, check=False):
        calls.append(list(args))
        # ``crontab -l``: rc=1 + "no crontab" → _read_crontab 归一为空串
        return _cp(1, stderr="no crontab for testuser")

    monkeypatch.setattr(ssb, "_run_text", fake_run_text)

    backend.unregister(_UUID)  # 不应抛异常

    # 仅 crontab -l 被调用；idempotent 早退路径下不应触碰 crontab -r / crontab -
    assert calls == [["crontab", "-l"]]


def test_linux_unregister_marker_missing_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """crontab 存在但目标 marker 不在其中（已被外部途径 `crontab -e` /
    `crontab -r` 删除）时，unregister 幂等成功而不阻塞 delete 流程。"""
    backend = LinuxBackend()
    existing_crontab = "# some unrelated comment\n* * * * * echo hi\n"
    calls: list[list[str]] = []
    written: list[str] = []

    def fake_run_text(args, check=False):
        calls.append(list(args))
        return _cp(0, stdout=existing_crontab)

    monkeypatch.setattr(ssb, "_run_text", fake_run_text)
    monkeypatch.setattr(
        backend, "_write_crontab", lambda content: written.append(content)
    )

    backend.unregister(_UUID)  # 不应抛异常

    # marker 缺失 → idempotent 早退：仅 crontab -l 被调用，不写入
    assert calls == [["crontab", "-l"]]
    assert written == []


def test_linux_unregister_read_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``crontab -l`` 真实失败（非「no crontab」语义）必须抛 RuntimeError，
    不被幂等语义吞掉。"""
    backend = LinuxBackend()
    monkeypatch.setattr(
        ssb,
        "_run_text",
        lambda args, check=False: _cp(1, stderr="command not found"),
    )

    with pytest.raises(RuntimeError, match="crontab -l failed"):
        backend.unregister(_UUID)


def test_linux_unregister_write_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """marker 找到且删后 crontab 仍非空，但 ``crontab -`` 写入失败
    （真实错误）必须抛 RuntimeError，不因幂等语义被吞掉。"""
    backend = LinuxBackend()
    # 「目标 marker + 其命令行」+ 「不相关用户条目」：删后剩余非空 → 走写入路径
    existing_crontab = (
        f"# MWU:{_UUID}\n* * * * * echo hi\n# unrelated\n0 0 * * * echo cleanup\n"
    )

    # ``crontab -l`` 返回已有 marker 的多行 crontab → 进入写入路径
    monkeypatch.setattr(
        ssb,
        "_run_text",
        lambda args, check=False: _cp(0, stdout=existing_crontab),
    )

    def boom_write(content: str) -> None:
        raise RuntimeError("crontab 写入失败: permission denied")

    monkeypatch.setattr(backend, "_write_crontab", boom_write)

    with pytest.raises(RuntimeError, match="crontab 写入失败"):
        backend.unregister(_UUID)


def test_linux_unregister_remove_command_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """marker 找到且删后 crontab 为空 → 走 ``crontab -r``；该 subprocess
    真实失败时必须抛 RuntimeError，不因幂等语义被吞掉。"""
    backend = LinuxBackend()
    # 「目标 marker + 其命令行」是唯一条目：删后剩余为空 → 走 crontab -r
    existing_crontab = f"# MWU:{_UUID}\n* * * * * echo hi\n"

    recorded: list[list[str]] = []

    def fake_run_text(args, check=False):
        recorded.append(list(args))
        # crontab -l 成功；crontab -r 真实失败
        if args == ["crontab", "-l"]:
            return _cp(0, stdout=existing_crontab)
        if args == ["crontab", "-r"]:
            return _cp(1, stderr="crontab: can't remove")
        raise AssertionError(f"unexpected _run_text call: {args}")

    monkeypatch.setattr(ssb, "_run_text", fake_run_text)

    with pytest.raises(RuntimeError, match="crontab -r failed"):
        backend.unregister(_UUID)
    assert recorded == [["crontab", "-l"], ["crontab", "-r"]]
