"""system_scope on APS jobs, scope import, repair-from-APS, lifespan order."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger

from models.scheduler import (
    CronTriggerConfig,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemTaskOperationalRecord,
    SystemTaskScope,
)
from scheduler_job_codec import (
    SchedulerJobDecodeError,
    build_trigger,
    decode_job_to_scheduled_task,
    encode_execution_kwargs,
)
from scheduler_manager import SchedulerManager, execute_scheduled_task
from services.system_scheduler import SystemTaskService, _SystemTaskState

TID_USER = "11111111-1111-1111-1111-111111111111"
TID_SYS = "22222222-2222-2222-2222-222222222222"
TID_JSON_ONLY = "33333333-3333-3333-3333-333333333333"
LEGACY_PRE = [{"id": "l1", "command": "echo legacy", "enabled": True, "timeout": 30}]


def _identity_normalize(task_list, task_options, pre_tasks):
    return list(task_list or []), dict(task_options or {}), list(pre_tasks or [])


# ---------------------------------------------------------------------------
# Codec scope
# ---------------------------------------------------------------------------


def test_encode_decode_system_scope_round_trip():
    # None stays None; user and legacy system both normalize to user wakeup.
    cases = [(None, None), ("user", "user"), ("system", "user")]
    for input_scope, expected in cases:
        kwargs = encode_execution_kwargs(
            task_id="t",
            task_name="n",
            task_description="",
            task_list=["Main"],
            task_options={},
            pre_tasks=[],
            controller_name=None,
            device=None,
            resource_name=None,
            system_scope=input_scope,  # type: ignore[arg-type]
        )
        assert "system_scope" in kwargs
        assert kwargs["system_scope"] is expected
        job = SimpleNamespace(
            id="t",
            kwargs=kwargs,
            trigger=build_trigger(CronTriggerConfig(cron="0 9 * * *")),
            next_run_time=None,
        )
        task = decode_job_to_scheduled_task(job, normalize=_identity_normalize)
        assert task.system_scope is expected


def test_decode_legacy_system_scope_string_as_user():
    """Persisted kwargs system_scope='system' decode as user wakeup."""
    job = SimpleNamespace(
        id="legacy-sys",
        kwargs={
            "task_name": "n",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
            "system_scope": "system",
        },
        trigger=build_trigger(CronTriggerConfig(cron="0 9 * * *")),
        next_run_time=None,
    )
    task = decode_job_to_scheduled_task(job, normalize=_identity_normalize)
    assert task.system_scope == "user"


def test_decode_invalid_system_scope_raises():
    job = SimpleNamespace(
        id="bad-scope",
        kwargs={
            "task_name": "n",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
            "system_scope": "admin",
        },
        trigger=build_trigger(CronTriggerConfig(cron="0 9 * * *")),
        next_run_time=None,
    )
    with pytest.raises(SchedulerJobDecodeError, match="invalid system_scope"):
        decode_job_to_scheduled_task(job, normalize=_identity_normalize)


@pytest.mark.asyncio
async def test_callable_accepts_and_ignores_system_scope():
    captured: dict[str, Any] = {}

    async def _execute_task(**kwargs):
        captured.update(kwargs)

    mock_mgr = MagicMock()
    mock_mgr._execute_task = AsyncMock(side_effect=_execute_task)
    with patch("scheduler_manager._ACTIVE_MANAGER", mock_mgr):
        await execute_scheduled_task(
            task_id="t",
            task_name="n",
            task_description="",
            task_list=["Main"],
            task_options={},
            pre_tasks=[],
            system_scope="user",
        )
    assert "system_scope" not in captured
    mock_mgr._execute_task.assert_awaited_once()


# ---------------------------------------------------------------------------
# Manager create/update scope
# ---------------------------------------------------------------------------


@pytest.fixture
async def manager(tmp_path: Path):
    mgr = SchedulerManager()
    mgr._db_path = tmp_path / "scheduler.sqlite"
    await mgr.initialize(start_scheduler=True, paused=True)
    assert mgr.scheduler is not None
    try:
        yield mgr
    finally:
        await mgr.shutdown()


def _create(**overrides: Any) -> ScheduledTaskCreate:
    data: dict[str, Any] = {
        "name": "scope-task",
        "trigger_type": "cron",
        "trigger_config": CronTriggerConfig(cron="0 9 * * *"),
        "task_list": ["Main"],
        "enabled": False,
    }
    data.update(overrides)
    return ScheduledTaskCreate(**data)


@pytest.mark.asyncio
async def test_create_writes_system_scope(manager: SchedulerManager):
    task = await manager.create_task(_create(system_scope="user"))
    assert task.system_scope == "user"
    assert manager.scheduler is not None
    job = manager.scheduler.get_job(task.id)
    assert job is not None
    assert job.kwargs["system_scope"] == "user"
    assert job.func_ref == "scheduler_manager:execute_scheduled_task"


@pytest.mark.asyncio
async def test_update_preserves_and_clears_system_scope(manager: SchedulerManager):
    # Legacy create with system_scope="system" is normalized to user on write.
    task = await manager.create_task(_create(system_scope="system"))
    assert task.system_scope == "user"
    assert manager.scheduler is not None
    assert manager.scheduler.get_job(task.id).kwargs["system_scope"] == "user"
    # omit system_scope → preserve user wakeup
    updated = await manager.update_task(task.id, ScheduledTaskUpdate(name="renamed"))
    assert updated is not None
    assert updated.system_scope == "user"
    assert manager.scheduler.get_job(task.id).kwargs["system_scope"] == "user"

    # explicit None → clear
    cleared = await manager.update_task(
        task.id, ScheduledTaskUpdate(system_scope=None)
    )
    assert cleared is not None
    assert cleared.system_scope is None
    assert manager.scheduler.get_job(task.id).kwargs["system_scope"] is None


# ---------------------------------------------------------------------------
# Real paused SQLite + legacy JSON import
# ---------------------------------------------------------------------------


def _seed_operational(
    svc: SystemTaskService,
    rows: list[tuple[str, str, SystemTaskScope, str]],
) -> None:
    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    for tid, _name, scope, _cron in rows:
        st.records.append(
            SystemTaskOperationalRecord(
                task_id=tid,
                platform="windows",
                state="active",
                last_known_scope=scope,
                cleanup_scopes=[scope],
                system_task_identifier=f"\\MWU\\{tid}",
                registered_exe_path="/usr/bin/mwu",
                last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
            )
        )
    svc._memory_state = st
    svc._save_state(st)


@pytest.mark.asyncio
async def test_import_scopes_user_system_idempotent_preserves_kwargs(
    tmp_path: Path,
):
    db = tmp_path / "scheduler.sqlite"
    mgr = SchedulerManager()
    mgr._db_path = db
    await mgr.initialize(start_scheduler=True, paused=True)
    assert mgr.scheduler is not None

    # User job: disabled, legacy preTasks key
    mgr.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*"),
        id=TID_USER,
        kwargs={
            "task_id": TID_USER,
            "task_name": "user-job",
            "task_description": "desc-u",
            "task_list": ["Main"],
            "task_options": {"Main": {"a": "1"}},
            "preTasks": LEGACY_PRE,
            "controller_name": "ADB",
            "device": None,
            "resource_name": "Official",
        },
    )
    mgr.scheduler.pause_job(TID_USER)

    # System job: enabled-ish next_run may exist; canonical pre_tasks
    mgr.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="30", hour="10", day="*", month="*", day_of_week="*"),
        id=TID_SYS,
        kwargs={
            "task_id": TID_SYS,
            "task_name": "sys-job",
            "task_description": "",
            "task_list": ["Side"],
            "task_options": {},
            "pre_tasks": [],
            "controller_name": None,
            "device": None,
            "resource_name": None,
        },
    )

    before_user = dict(mgr.scheduler.get_job(TID_USER).kwargs)
    before_user_func = mgr.scheduler.get_job(TID_USER).func_ref
    before_user_paused = mgr.scheduler.get_job(TID_USER).next_run_time is None
    before_sys_func = mgr.scheduler.get_job(TID_SYS).func_ref

    svc = SystemTaskService(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    _seed_operational(
        svc,
        [
            (TID_USER, "json-user-name", SystemTaskScope.USER, "0 9 * * *"),
            (TID_SYS, "json-sys-name", SystemTaskScope.SYSTEM, "30 10 * * *"),
            (TID_JSON_ONLY, "json-only", SystemTaskScope.USER, "0 0 * * *"),
        ],
    )

    stats1 = await svc.import_scopes_into_aps(mgr)
    assert stats1["imported"] == 2
    assert stats1["missing_job"] == 1  # JSON-only
    assert stats1["failed"] == 0

    user_job = mgr.scheduler.get_job(TID_USER)
    sys_job = mgr.scheduler.get_job(TID_SYS)
    assert user_job is not None and sys_job is not None
    # Both USER and legacy SYSTEM operational scopes import as user wakeup.
    assert user_job.kwargs["system_scope"] == "user"
    assert sys_job.kwargs["system_scope"] == "user"
    # legacy keys preserved
    assert user_job.kwargs.get("preTasks") == LEGACY_PRE
    assert "pre_tasks" not in user_job.kwargs or user_job.kwargs.get("preTasks")
    assert user_job.kwargs["task_options"] == before_user["task_options"]
    assert user_job.func_ref == before_user_func == "scheduler_manager:execute_scheduled_task"
    assert sys_job.func_ref == before_sys_func
    assert (user_job.next_run_time is None) == before_user_paused
    assert isinstance(user_job.trigger, CronTrigger)

    # JSON-only must not create APS job
    assert mgr.scheduler.get_job(TID_JSON_ONLY) is None

    # Idempotent second run
    stats2 = await svc.import_scopes_into_aps(mgr)
    assert stats2["imported"] == 0
    assert stats2["skipped"] == 2
    assert stats2["missing_job"] == 1

    # Durable: close and reopen store
    await mgr.shutdown()
    mgr2 = SchedulerManager()
    mgr2._db_path = db
    await mgr2.initialize(start_scheduler=True, paused=True)
    assert mgr2.scheduler is not None
    u2 = mgr2.scheduler.get_job(TID_USER)
    s2 = mgr2.scheduler.get_job(TID_SYS)
    assert u2 is not None and u2.kwargs.get("system_scope") == "user"
    assert s2 is not None and s2.kwargs.get("system_scope") == "user"
    assert u2.kwargs.get("preTasks") == LEGACY_PRE
    assert u2.func_ref == "scheduler_manager:execute_scheduled_task"
    assert u2.next_run_time is None  # still paused/disabled
    await mgr2.shutdown()


@pytest.mark.asyncio
async def test_import_corrupt_json_fail_closed(tmp_path: Path, manager: SchedulerManager):
    svc = SystemTaskService(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    svc._state_file.write_text("{not json", encoding="utf-8")
    stats = await svc.import_scopes_into_aps(manager)
    assert stats["imported"] == 0
    assert stats["failed"] == 1  # visible failure for lifespan logging
    assert any("corrupt" in d for d in stats["details"])
    # file preserved (backup may exist)
    assert svc._state_file.exists()


@pytest.mark.asyncio
async def test_import_does_not_overwrite_aps_present_key(
    tmp_path: Path, manager: SchedulerManager
):
    """JSON must not overwrite APS when system_scope key is already present."""
    assert manager.scheduler is not None
    # Present None
    manager.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*"),
        id=TID_USER,
        kwargs={
            "task_id": TID_USER,
            "task_name": "u",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
            "system_scope": None,
        },
    )
    manager.scheduler.pause_job(TID_USER)
    # Present user while JSON wants system
    manager.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="10", day="*", month="*", day_of_week="*"),
        id=TID_SYS,
        kwargs={
            "task_id": TID_SYS,
            "task_name": "s",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
            "system_scope": "user",
        },
    )
    manager.scheduler.pause_job(TID_SYS)

    svc = SystemTaskService(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    _seed_operational(
        svc,
        [
            (TID_USER, "json", SystemTaskScope.USER, "0 9 * * *"),
            (TID_SYS, "json", SystemTaskScope.SYSTEM, "0 10 * * *"),
        ],
    )
    stats = await svc.import_scopes_into_aps(manager)
    assert stats["imported"] == 0
    assert stats["skipped"] == 2
    assert manager.scheduler.get_job(TID_USER).kwargs["system_scope"] is None
    assert manager.scheduler.get_job(TID_SYS).kwargs["system_scope"] == "user"


# ---------------------------------------------------------------------------
# Lifespan order + headless remains paused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_order_paused_import_repair_resume(
    main_module, tmp_path: Path, monkeypatch
):
    """Web lifespan: paused init → import → repair → resume."""
    order: list[str] = []

    class FakeScheduler:
        def __init__(self):
            self.resumed = False

        def resume(self):
            self.resumed = True
            order.append("resume")

    class FakeManager:
        def __init__(self):
            self.scheduler = FakeScheduler()
            self.init_kwargs: dict[str, Any] = {}

        def set_worker(self, w):
            order.append("set_worker")

        async def initialize(self, **kw):
            self.init_kwargs = kw
            order.append("init")
            assert kw.get("paused") is True

        async def shutdown(self):
            order.append("shutdown")

    class FakeService:
        def __init__(self, root):
            order.append("service_ctor")

        async def import_scopes_into_aps(self, manager):
            order.append("import")
            assert manager.scheduler.resumed is False
            return {"imported": 0, "skipped": 0, "missing_job": 0, "failed": 0}

        async def repair_all(self, manager=None):
            order.append("repair")
            assert manager is not None
            assert manager.scheduler.resumed is False
            return {"repaired": 0, "failed": 0, "details": []}

    monkeypatch.setattr(main_module, "SchedulerManager", FakeManager)
    monkeypatch.setattr(main_module, "SystemTaskService", FakeService)
    monkeypatch.setattr(main_module, "MaaWorker", lambda *a, **k: MagicMock())
    monkeypatch.setattr(main_module, "LogBroadcaster", lambda: MagicMock())
    monkeypatch.setattr(main_module, "log_monitor", AsyncMock())
    monkeypatch.setattr(main_module, "webbrowser", SimpleNamespace(open_new=lambda *_: None))
    monkeypatch.setattr(main_module, "release_runtime_ownership", lambda: None)
    monkeypatch.setattr(main_module.app_state, "send_log", lambda *_a, **_k: None)
    monkeypatch.setattr(main_module.app_state, "message_conn", MagicMock())
    monkeypatch.setattr(main_module.app_state, "worker", None)
    monkeypatch.setattr(main_module.app_state, "broadcaster", None)
    monkeypatch.setattr(main_module.app_state, "scheduler_manager", None)
    monkeypatch.setattr(main_module.app_state, "system_scheduler", None)

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(main_module, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(main_module, "APP_ROOT_DIR", tmp_path)

    # Minimal SettingsModel validate
    with patch(
        "main.SettingsModel.model_validate",
        return_value=MagicMock(),
    ), patch("main.interface_lock"):
        async with main_module.lifespan(MagicMock()):
            assert order == [
                "set_worker",
                "init",
                "service_ctor",
                "import",
                "repair",
                "resume",
            ]
            assert main_module.app_state.scheduler_manager.init_kwargs.get("paused") is True
            assert main_module.app_state.scheduler_manager.scheduler.resumed is True


@pytest.mark.asyncio
async def test_headless_stays_paused(main_module, tmp_path, monkeypatch):
    """Headless initialize remains paused; no resume path."""
    monkeypatch.setattr(main_module, "APP_ROOT_DIR", tmp_path)
    monkeypatch.setattr(main_module, "LOGS_DIR", tmp_path / "config" / "logs")
    (tmp_path / "config" / "logs").mkdir(parents=True)

    ownership = MagicMock()
    monkeypatch.setattr(main_module, "acquire_runtime_ownership", lambda: ownership)
    monkeypatch.setattr(main_module, "release_runtime_ownership", lambda: None)

    seen: dict[str, Any] = {}

    class SM:
        def set_worker(self, w):
            pass

        async def initialize(self, **kw):
            seen["init"] = kw
            self.scheduler = MagicMock()
            self.scheduler.get_job.return_value = SimpleNamespace(
                next_run_time=None, kwargs={}
            )

        async def shutdown(self):
            pass

    monkeypatch.setattr(main_module, "SchedulerManager", SM)
    monkeypatch.setattr(
        main_module,
        "MaaWorker",
        lambda *a, **k: MagicMock(task_state=SimpleNamespace(last_status="failed")),
    )

    code = await main_module.run_headless(TID_USER)
    assert code == main_module.EXIT_TASK_FAILED
    assert seen["init"].get("paused") is True


@pytest.mark.asyncio
async def test_lifespan_corrupt_import_logs_details_then_resumes(
    main_module, tmp_path: Path, monkeypatch
):
    """Corrupt JSON yields failed>0 with details logged before APS resume."""
    logs: list[str] = []
    order: list[str] = []

    class FakeScheduler:
        def resume(self):
            order.append("resume")

    class FakeManager:
        def __init__(self):
            self.scheduler = FakeScheduler()

        def set_worker(self, w):
            pass

        async def initialize(self, **kw):
            order.append("init")
            assert kw.get("paused") is True

        async def shutdown(self):
            pass

    class FakeService:
        def __init__(self, root):
            pass

        async def import_scopes_into_aps(self, manager):
            order.append("import")
            return {
                "imported": 0,
                "skipped": 0,
                "missing_job": 0,
                "failed": 1,
                "details": ["system_tasks.json corrupt; scope import refused"],
            }

        async def repair_all(self, manager=None):
            order.append("repair")
            return {
                "repaired": 0,
                "failed": 1,
                "details": ["state corrupt; repair refused"],
            }

    monkeypatch.setattr(main_module, "SchedulerManager", FakeManager)
    monkeypatch.setattr(main_module, "SystemTaskService", FakeService)
    monkeypatch.setattr(main_module, "MaaWorker", lambda *a, **k: MagicMock())
    monkeypatch.setattr(main_module, "LogBroadcaster", lambda: MagicMock())
    monkeypatch.setattr(main_module, "log_monitor", AsyncMock())
    monkeypatch.setattr(
        main_module, "webbrowser", SimpleNamespace(open_new=lambda *_: None)
    )
    monkeypatch.setattr(main_module, "release_runtime_ownership", lambda: None)
    monkeypatch.setattr(
        main_module.app_state, "send_log", lambda msg, *a, **k: logs.append(str(msg))
    )
    monkeypatch.setattr(main_module.app_state, "message_conn", MagicMock())
    monkeypatch.setattr(main_module.app_state, "worker", None)
    monkeypatch.setattr(main_module.app_state, "broadcaster", None)
    monkeypatch.setattr(main_module.app_state, "scheduler_manager", None)
    monkeypatch.setattr(main_module.app_state, "system_scheduler", None)

    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(main_module, "SETTINGS_FILE", settings_file)
    monkeypatch.setattr(main_module, "APP_ROOT_DIR", tmp_path)

    with patch(
        "main.SettingsModel.model_validate", return_value=MagicMock()
    ), patch("main.interface_lock"):
        async with main_module.lifespan(MagicMock()):
            assert order == ["init", "import", "repair", "resume"]
            assert any("corrupt" in m and "failed=1" in m for m in logs)
            assert any("修复" in m or "repair" in m.lower() or "失败" in m for m in logs)
            # resume after failure logs
            corrupt_idx = next(i for i, m in enumerate(logs) if "corrupt" in m)
            resume_idx = next(i for i, m in enumerate(logs) if "恢复派发" in m)
            assert corrupt_idx < resume_idx
