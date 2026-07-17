"""Reconciler matrix tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.triggers.cron import CronTrigger

from models.scheduler import (
    CronTriggerConfig,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemTaskOperationalRecord,
    SystemTaskScope,
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
        build_identifier=MagicMock(side_effect=lambda tid, s: f"\\MWU\\{s.value}\\{tid}"),
    )


def _caps():
    return (
        patch(
            "services.system_scheduler.is_capability_enabled",
            return_value=(True, "enabled", []),
        ),
        patch(
            "services.system_scheduler.validate_trigger_for_platform", return_value=[]
        ),
    )


def _seed(
    svc: SystemTaskService,
    *,
    scope: SystemTaskScope = SystemTaskScope.USER,
    cron: str = "0 9 * * *",
    name: str = "task",
    state: str = "active",
    exe: str = "/old/mwu",
) -> None:
    del cron, name
    op = "error" if state in ("error", "orphaned", "pending_register", "pending_cleanup") else "active"
    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=TID,
            platform="windows",
            state=op,  # type: ignore[arg-type]
            last_known_scope=scope,
            cleanup_scopes=[scope],
            system_task_identifier=f"\\MWU\\{TID}",
            registered_exe_path=exe,
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
            last_error="pending" if op == "error" else None,
        )
    )
    svc._memory_state = st
    svc._save_state(st)


def _aps_task(
    *,
    name: str = "task",
    cron: str = "0 9 * * *",
    scope: str | None = "user",
) -> ScheduledTask:
    return ScheduledTask(
        id=TID,
        name=name,
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
        system_scope=scope,  # type: ignore[arg-type]
    )


def _mgr(task: ScheduledTask | None = None, *, missing=False, decode_err=False):
    mgr = MagicMock()
    if decode_err:
        mgr.get_task = AsyncMock(
            side_effect=SchedulerJobDecodeError("bad", job_id=TID)
        )
        mgr.job_has_system_scope_key = MagicMock(return_value=True)
        mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
        return mgr
    if missing:
        mgr.get_task = AsyncMock(return_value=None)
        mgr.job_has_system_scope_key = MagicMock(return_value=None)
        mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
        return mgr
    t = task or _aps_task()
    mgr.get_task = AsyncMock(return_value=t)
    mgr.job_has_system_scope_key = MagicMock(
        return_value=t.system_scope is not None or True
    )
    if t.system_scope is None:
        # key present with None
        mgr.job_has_system_scope_key = MagicMock(return_value=True)
    else:
        mgr.job_has_system_scope_key = MagicMock(return_value=True)
    mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
    return mgr


@pytest.mark.asyncio
async def test_reconcile_noop_when_converged(service, backend):
    service._backend = backend
    exe = service.current_exe_path
    _seed(service, exe=exe)
    backend.is_registered = AsyncMock(return_value=True)
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    t = _aps_task()
    caps, trig = _caps()
    with caps, trig:
        st = service._load_state()
        reg = service._find_registration(st, TID)
        assert reg
        reg.registered_exe_path = exe
        reg.last_known_scope = SystemTaskScope.USER
        reg.state = "active"
        service._save_state(st)
        result = await service.reconcile_task(_mgr(t), TID)
    assert result.action == "noop"
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_missing_native_registers(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=False)
    caps, trig = _caps()
    with caps, trig:
        result = await service.reconcile_task(_mgr(), TID)
    assert result.action in ("registered", "updated", "materialized")
    backend.register.assert_awaited()


@pytest.mark.asyncio
async def test_reconcile_stale_path_reregisters(service, backend):
    service._backend = backend
    _seed(service, exe="/stale/path")
    backend.is_registered = AsyncMock(return_value=True)
    caps, trig = _caps()
    with caps, trig:
        result = await service.reconcile_task(_mgr(), TID)
    assert result.action == "updated"
    assert "路径" in result.detail or "path" in result.detail.lower() or result.detail
    backend.register.assert_awaited()


@pytest.mark.asyncio
async def test_reconcile_scope_user_to_system_old_cleanup_order(service, backend):
    service._backend = backend
    _seed(service, scope=SystemTaskScope.USER)
    order: list[str] = []
    # USER starts present so cleanup must unregister; SYSTEM absent until reg.
    present = {SystemTaskScope.USER: True, SystemTaskScope.SYSTEM: False}

    async def unreg(_tid, scope):
        order.append(f"unreg:{scope.value}")
        present[scope] = False

    async def is_reg(_tid, scope):
        order.append(f"is:{scope.value}")
        return present[scope]

    async def reg(spec):
        order.append(f"reg:{spec.scope.value}")
        present[spec.scope] = True

    backend.unregister = AsyncMock(side_effect=unreg)
    backend.is_registered = AsyncMock(side_effect=is_reg)
    backend.register = AsyncMock(side_effect=reg)
    caps, trig = _caps()
    with caps, trig:
        result = await service.reconcile_task(
            _mgr(_aps_task(scope="system", cron="0 8 * * *", name="sys")),
            TID,
        )
    assert result.action != "error", result
    assert order.index("unreg:user") < order.index("reg:system")
    reg_row = service._find_registration(service._load_state(), TID)
    assert reg_row is not None
    assert reg_row.last_known_scope == SystemTaskScope.SYSTEM
    assert SystemTaskScope.USER in reg_row.cleanup_scopes


@pytest.mark.asyncio
async def test_reconcile_unknown_query_no_register(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(side_effect=RuntimeError("schtasks boom"))
    caps, trig = _caps()
    with caps, trig:
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
    caps, trig = _caps()
    with caps, trig:
        result = await service.reconcile_task(_mgr(), TID)
    assert result.action == "error"
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "error"


@pytest.mark.asyncio
async def test_reconcile_aps_missing_orphan_both_scopes(service, backend):
    service._backend = backend
    _seed(service)
    calls: list[str] = []

    async def is_reg(_tid, scope):
        calls.append(scope.value)
        return False

    backend.is_registered = AsyncMock(side_effect=is_reg)
    result = await service.reconcile_task(_mgr(missing=True), TID)
    assert result.action == "cleaned"
    assert service._find_registration(service._load_state(), TID) is None
    assert "user" in calls and "system" in calls
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_aps_explicit_none_cleans_record(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=False)
    t = _aps_task(scope=None)
    result = await service.reconcile_task(_mgr(t), TID)
    assert result.action == "cleaned"
    assert service._find_registration(service._load_state(), TID) is None
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_aps_scoped_no_json_materializes(service, backend):
    service._backend = backend
    # no seed — APS only
    backend.is_registered = AsyncMock(return_value=False)
    caps, trig = _caps()
    with caps, trig:
        result = await service.reconcile_task(_mgr(_aps_task()), TID)
    assert result.action == "materialized"
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "active"
    assert reg.last_known_scope == SystemTaskScope.USER


@pytest.mark.asyncio
async def test_reconcile_pending_and_error_processed(service, backend):
    service._backend = backend
    for st in ("pending_register", "error", "pending_cleanup"):
        _seed(service, state=st)
        backend.is_registered = AsyncMock(return_value=False)
        backend.register = AsyncMock()
        backend.verify_registration = AsyncMock(return_value=(True, "ok"))
        caps, trig = _caps()
        with caps, trig:
            result = await service.reconcile_task(_mgr(), TID)
        assert result.action in ("registered", "updated", "materialized")
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "active"


@pytest.mark.asyncio
async def test_reconcile_corrupt_aps_error_no_register(service, backend):
    service._backend = backend
    _seed(service)
    result = await service.reconcile_task(_mgr(decode_err=True), TID)
    assert result.action == "error"
    backend.register.assert_not_awaited()
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "error"


@pytest.mark.asyncio
async def test_second_reconcile_noop(service, backend):
    service._backend = backend
    exe = service.current_exe_path
    _seed(service, exe=exe)
    backend.is_registered = AsyncMock(return_value=False)
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    caps, trig = _caps()
    with caps, trig:
        r1 = await service.reconcile_task(_mgr(), TID)
        assert r1.action != "error"
        backend.register.reset_mock()
        backend.is_registered = AsyncMock(return_value=True)
        st = service._load_state()
        reg = service._find_registration(st, TID)
        assert reg and reg.state == "active"
        reg.registered_exe_path = exe
        service._save_state(st)
        r2 = await service.reconcile_task(_mgr(), TID)
    assert r2.action == "noop"
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rollback_certainty(service, backend, tmp_path):
    service._backend = backend
    backend.is_registered = AsyncMock(return_value=False)
    backend.register = AsyncMock(side_effect=RuntimeError("native boom"))
    mgr = MagicMock()
    task = _aps_task()
    mgr.create_task = AsyncMock(return_value=task)
    mgr.get_task = AsyncMock(return_value=task)
    mgr.job_has_system_scope_key = MagicMock(return_value=True)
    mgr.delete_task = AsyncMock(return_value=True)
    mgr.delete_task_classified = AsyncMock(return_value="success")
    mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
    caps, trig = _caps()
    with caps, trig, pytest.raises(RuntimeError, match="native"):
        await service.create_task_synced(
            mgr,
            ScheduledTaskCreate(
                name="task",
                trigger_type="cron",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                task_list=["Main"],
                system_scope="user",
            ),
        )
    mgr.delete_task.assert_awaited()


@pytest.mark.asyncio
async def test_update_partial_result_shape(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=False)
    backend.register = AsyncMock(side_effect=RuntimeError("native fail"))
    t = _aps_task()
    mgr = _mgr(t)
    mgr.update_task = AsyncMock(return_value=t)
    caps, trig = _caps()
    with caps, trig:
        result = await service.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(name="n")
        )
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert result.native_error is not None
    assert "native fail" in result.native_error or result.native_error


@pytest.mark.asyncio
async def test_delete_partial_native_incomplete(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=True)
    backend.unregister = AsyncMock()  # still present after
    mgr = MagicMock()
    mgr.delete_task = AsyncMock(return_value=True)
    mgr.delete_task_classified = AsyncMock(return_value="success")
    with pytest.raises(RuntimeError, match="partial delete"):
        await service.delete_task_synced(mgr, TID)
    mgr.delete_task_classified.assert_not_awaited()
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "error"


@pytest.mark.asyncio
async def test_reconcile_union_includes_invalid_scope_key(service, backend):
    """APS job with system_scope key present but invalid value → durable error."""
    service._backend = backend
    job = MagicMock()
    job.id = TID
    job.kwargs = {
        "task_id": TID,
        "task_name": "bad",
        "system_scope": "admin",  # invalid
    }
    mgr = MagicMock()
    mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[job]))
    mgr.get_task = AsyncMock(
        side_effect=SchedulerJobDecodeError("invalid system_scope: 'admin'", job_id=TID)
    )
    mgr.job_has_system_scope_key = MagicMock(return_value=True)
    result = await service.reconcile_all(mgr)
    assert result["failed"] == 1
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "error"
    assert "invalid system_scope" in (reg.last_error or "") or "decode" in (
        reg.last_error or ""
    ).lower()
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_success_removes_record(service, backend):
    service._backend = backend
    _seed(service)
    present = {"v": True}

    async def is_reg(*_a, **_k):
        return present["v"]

    async def unreg(*_a, **_k):
        present["v"] = False

    backend.is_registered = AsyncMock(side_effect=is_reg)
    backend.unregister = AsyncMock(side_effect=unreg)
    mgr = MagicMock()
    mgr.delete_task_classified = AsyncMock(return_value="success")
    assert await service.delete_task_synced(mgr, TID) is True
    assert service._find_registration(service._load_state(), TID) is None


@pytest.mark.asyncio
async def test_delete_aps_not_found_removes_record(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=False)
    mgr = MagicMock()
    mgr.delete_task_classified = AsyncMock(return_value="not_found")
    assert await service.delete_task_synced(mgr, TID) is True
    assert service._find_registration(service._load_state(), TID) is None


@pytest.mark.asyncio
async def test_delete_aps_indeterminate_retains_record(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=False)
    mgr = MagicMock()
    mgr.delete_task_classified = AsyncMock(return_value="indeterminate")
    with pytest.raises(RuntimeError, match="indeterminate"):
        await service.delete_task_synced(mgr, TID)
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "error"
    assert "indeterminate" in (reg.last_error or "")


@pytest.mark.asyncio
async def test_delete_no_prior_record_indeterminate_creates_error(service, backend):
    service._backend = backend
    # no seed
    backend.is_registered = AsyncMock(return_value=False)
    mgr = MagicMock()
    mgr.delete_task_classified = AsyncMock(return_value="indeterminate")
    with pytest.raises(RuntimeError, match="indeterminate"):
        await service.delete_task_synced(mgr, TID)
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "error"
    assert "indeterminate" in (reg.last_error or "")


@pytest.mark.asyncio
async def test_delete_synced_unknown_native_does_not_drop_record(service, backend):
    """Native presence unknown during delete keeps operational record."""
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(side_effect=RuntimeError("query boom"))
    mgr = MagicMock()
    mgr.delete_task_classified = AsyncMock(return_value="success")
    with pytest.raises(RuntimeError, match="partial delete|unknown|cleanup"):
        await service.delete_task_synced(mgr, TID)
    reg = service._find_registration(service._load_state(), TID)
    assert reg is not None and reg.state == "error"
    mgr.delete_task_classified.assert_not_awaited()


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
            "system_scope": "user",
        },
    )
    mgr.scheduler.pause_job(TID)

    caps, trig = _caps()
    with caps, trig:
        r1 = await svc.reconcile_task(mgr, TID)
        assert r1.action == "materialized"
        backend.is_registered = AsyncMock(return_value=True)
        r2 = await svc.reconcile_task(mgr, TID)
    assert r2.action == "noop"
    await mgr.shutdown()
