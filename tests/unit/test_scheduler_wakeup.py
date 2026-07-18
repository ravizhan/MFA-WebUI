"""wakeup_enabled: execute ignore, manager explicit disable, lifespan order."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import CronTriggerConfig, ScheduledTaskCreate, ScheduledTaskUpdate
from scheduler_manager import SchedulerManager, execute_scheduled_task

TID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
async def test_callable_accepts_and_ignores_wakeup_enabled():
    captured: dict[str, Any] = {}

    async def _execute_task(**kwargs):
        captured.update(kwargs)

    mock_mgr = MagicMock()
    mock_mgr._execute_task = AsyncMock(side_effect=_execute_task)

    with patch("scheduler_manager._ACTIVE_MANAGER", mock_mgr):
        await execute_scheduled_task(
            task_id=TID,
            task_name="t",
            task_description="",
            task_list=["Main"],
            task_options={},
            wakeup_enabled=True,
        )

    mock_mgr._execute_task.assert_awaited_once()
    assert "wakeup_enabled" not in captured


# ---------------------------------------------------------------------------
# Manager create / update
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
        "name": "wakeup-task",
        "trigger_type": "cron",
        "trigger_config": CronTriggerConfig(cron="0 9 * * *"),
        "task_list": ["Main"],
        "enabled": False,
    }
    data.update(overrides)
    return ScheduledTaskCreate(**data)


@pytest.mark.asyncio
async def test_update_explicit_false_disables_wakeup(manager: SchedulerManager):
    task = await manager.create_task(_create(wakeup_enabled=True))
    cleared = await manager.update_task(
        task.id, ScheduledTaskUpdate(wakeup_enabled=False)
    )
    assert cleared is not None
    assert cleared.wakeup_enabled is False
    assert manager.scheduler is not None
    assert manager.scheduler.get_job(task.id).kwargs["wakeup_enabled"] is False


# ---------------------------------------------------------------------------
# Lifespan: initialize → repair → resume (no import/migration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_order_paused_repair_resume(
    main_module, tmp_path: Path, monkeypatch
):
    """Web lifespan: paused init → repair → resume (no scope import)."""
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
    monkeypatch.setattr(
        main_module, "webbrowser", SimpleNamespace(open_new=lambda *_: None)
    )
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

    with patch(
        "main.SettingsModel.model_validate",
        return_value=MagicMock(),
    ), patch("main.interface_lock"):
        async with main_module.lifespan(MagicMock()):
            assert order == [
                "set_worker",
                "init",
                "service_ctor",
                "repair",
                "resume",
            ]
            assert "import" not in order
            assert main_module.app_state.scheduler_manager.init_kwargs.get("paused") is True
            assert main_module.app_state.scheduler_manager.scheduler.resumed is True


@pytest.mark.asyncio
async def test_lifespan_repair_failure_still_resumes(
    main_module, tmp_path: Path, monkeypatch
):
    """Corrupt/repair failure is logged; APS still resumes."""
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
            assert order == ["init", "repair", "resume"]
            assert any("失败" in m or "failed" in m.lower() or "修复" in m for m in logs)
            resume_idx = next(i for i, m in enumerate(logs) if "恢复派发" in m)
            fail_idx = next(
                i
                for i, m in enumerate(logs)
                if "失败" in m or "failed" in m.lower() or "修复" in m
            )
            assert fail_idx < resume_idx
