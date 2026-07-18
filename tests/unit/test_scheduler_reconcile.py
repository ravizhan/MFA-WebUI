"""Reconciler matrix tests for wakeup_enabled native coordination."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger

from models.scheduler import (
    OPERATIONAL_STATE_VERSION,
    CronTriggerConfig,
    ScheduledTask,
    SystemTaskOperationalRecord,
)
from scheduler_job_codec import SchedulerJobDecodeError
from scheduler_manager import SchedulerManager, execute_scheduled_task
from services.system_scheduler import SystemTaskService, _SystemTaskState

TID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def service(tmp_path: Path) -> SystemTaskService:
    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    return SystemTaskService(tmp_path)


@pytest.fixture
def backend():
    return MagicMock(
        platform_name="windows",
        register=AsyncMock(),
        unregister=AsyncMock(),
        is_registered=AsyncMock(return_value=False),
        verify_registration=AsyncMock(return_value=(True, "ok")),
        build_identifier=MagicMock(side_effect=lambda tid: f"\\MWU\\{tid}"),
    )


def _trig():
    return patch(
        "services.system_scheduler.validate_trigger_for_platform", return_value=[]
    )


def _seed(
    svc: SystemTaskService,
    *,
    state: str = "active",
    exe: str = "/old/mwu",
) -> None:
    op = "error" if state == "error" else "active"
    st = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=TID,
            platform="windows",
            state=op,  # type: ignore[arg-type]
            registered_exe_path=exe,
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
            last_error="pending" if op == "error" else None,
        )
    )
    svc._save_state(st)


def _aps_task(
    *,
    name: str = "task",
    cron: str = "0 9 * * *",
    wakeup_enabled: bool = True,
) -> ScheduledTask:
    return ScheduledTask(
        id=TID,
        name=name,
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
        wakeup_enabled=wakeup_enabled,
    )


def _mgr(task: ScheduledTask | None = None, *, missing=False, decode_err=False):
    mgr = MagicMock()
    if decode_err:
        mgr.get_task = AsyncMock(
            side_effect=SchedulerJobDecodeError("bad", job_id=TID)
        )
        mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
        return mgr
    if missing:
        mgr.get_task = AsyncMock(return_value=None)
        mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
        return mgr
    t = task or _aps_task()
    mgr.get_task = AsyncMock(return_value=t)
    mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
    return mgr


def _find(svc: SystemTaskService):
    return svc._find_record(svc._load_state(), TID)


@pytest.mark.asyncio
async def test_reconcile_stale_path_reregisters(service, backend):
    service._backend = backend
    _seed(service, exe="/stale/path")
    backend.is_registered = AsyncMock(return_value=True)
    with _trig():
        result = await service.reconcile_task(_mgr(), TID)
    assert result.action == "updated"
    assert result.detail
    backend.register.assert_awaited()


@pytest.mark.asyncio
async def test_reconcile_unknown_query_no_register(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(side_effect=RuntimeError("schtasks boom"))
    with _trig():
        result = await service.reconcile_task(_mgr(), TID)
    assert result.action == "error"
    assert "unknown" in (result.native_error or "").lower()
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_failed_register_persists_error(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=False)
    backend.register = AsyncMock(side_effect=RuntimeError("reg boom"))
    with _trig():
        result = await service.reconcile_task(_mgr(), TID)
    assert result.action == "error"
    reg = _find(service)
    assert reg is not None and reg.state == "error"


@pytest.mark.asyncio
async def test_reconcile_aps_missing_cleans_record(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=False)
    result = await service.reconcile_task(_mgr(missing=True), TID)
    assert result.action == "cleaned"
    assert _find(service) is None
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_error_state_reregisters(service, backend):
    service._backend = backend
    _seed(service, state="error")
    backend.is_registered = AsyncMock(return_value=False)
    backend.register = AsyncMock()
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    with _trig():
        result = await service.reconcile_task(_mgr(), TID)
    assert result.action in ("registered", "updated", "materialized")
    reg = _find(service)
    assert reg is not None and reg.state == "active"


@pytest.mark.asyncio
async def test_reconcile_corrupt_aps_error_no_register(service, backend):
    service._backend = backend
    _seed(service)
    result = await service.reconcile_task(_mgr(decode_err=True), TID)
    assert result.action == "error"
    backend.register.assert_not_awaited()
    reg = _find(service)
    assert reg is not None and reg.state == "error"


@pytest.mark.asyncio
async def test_reconcile_all_invalid_wakeup_decode_error(service, backend):
    """APS job with invalid wakeup_enabled → durable error."""
    service._backend = backend
    job = MagicMock()
    job.id = TID
    job.kwargs = {
        "task_id": TID,
        "task_name": "bad",
        "wakeup_enabled": "admin",
    }
    mgr = MagicMock()
    mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[job]))
    mgr.get_task = AsyncMock(
        side_effect=SchedulerJobDecodeError(
            "invalid wakeup_enabled: 'admin'", job_id=TID
        )
    )
    # Only union jobs with wakeup_enabled True; invalid string is truthy in kwargs
    # but get_task will fail when reconcile_all iterates. Force inclusion via record.
    _seed(service)
    result = await service.reconcile_all(mgr)
    assert result["failed"] >= 1
    reg = _find(service)
    assert reg is not None and reg.state == "error"
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_paused_sqlite_materialize_and_second_noop(tmp_path, backend):
    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# m", encoding="utf-8")
    svc = SystemTaskService(tmp_path)
    svc._backend = backend
    backend.is_registered = AsyncMock(return_value=False)

    mgr = SchedulerManager()
    mgr._db_path = tmp_path / "scheduler.sqlite"
    await mgr.initialize(start_scheduler=True, paused=True)
    assert mgr.scheduler is not None
    mgr.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*"),
        id=TID,
        kwargs={
            "task_id": TID,
            "task_name": "real",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {},
            "pre_tasks": [],
            "wakeup_enabled": True,
        },
    )
    mgr.scheduler.pause_job(TID)

    with _trig():
        r1 = await svc.reconcile_task(mgr, TID)
        assert r1.action == "materialized"
        backend.is_registered = AsyncMock(return_value=True)
        r2 = await svc.reconcile_task(mgr, TID)
    assert r2.action == "noop"
    await mgr.shutdown()
