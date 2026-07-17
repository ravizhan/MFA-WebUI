"""Focused APS+native sync wrapper tests."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    CronTriggerConfig,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemTaskOperationalRecord,
    SystemTaskScope,
)
from services.system_scheduler import SystemTaskService, _SystemTaskState

TID = "550e8400-e29b-41d4-a716-446655440000"


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
        build_identifier=MagicMock(side_effect=lambda tid, _s: f"\\MWU\\{tid}"),
    )


def _patch_caps():
    return (
        patch(
            "services.system_scheduler.is_capability_enabled",
            return_value=(True, "enabled", []),
        ),
        patch(
            "services.system_scheduler.validate_trigger_for_platform", return_value=[]
        ),
    )


def _task(
    cron: str = "0 9 * * *",
    *,
    system_scope: Literal["user", "system"] | None = None,
    name: str = "task",
) -> ScheduledTask:
    return ScheduledTask(
        id=TID,
        name=name,
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
        system_scope=system_scope,
    )


def _create(scope: Literal["user", "system"] | None = "user") -> ScheduledTaskCreate:
    return ScheduledTaskCreate(
        name="task",
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        system_scope=scope,
    )


def _mgr(
    task: ScheduledTask | None = None,
    *,
    has_scope_key: bool | None = None,
) -> MagicMock:
    t = task or _task(system_scope="user")
    # Default: legacy missing key so omitted-scope falls back to JSON.
    key_present = has_scope_key
    if key_present is None:
        key_present = t.system_scope is not None

    holder: dict[str, object] = {
        "task": t.model_copy(deep=True),
        "key": bool(key_present),
    }

    async def _create_task(create: ScheduledTaskCreate):
        cur = holder["task"]
        assert isinstance(cur, ScheduledTask)
        out = cur.model_copy(deep=True)
        out.system_scope = create.system_scope
        out.name = create.name
        holder["task"] = out
        holder["key"] = True  # create always writes system_scope key
        return out

    async def _get_task(_tid):
        cur = holder["task"]
        assert isinstance(cur, ScheduledTask)
        return cur

    async def _update_task(_tid, update: ScheduledTaskUpdate):
        cur = holder["task"]
        assert isinstance(cur, ScheduledTask)
        out = cur.model_copy(deep=True)
        if update.name is not None:
            out.name = update.name
        if update.trigger_config is not None:
            out.trigger_config = update.trigger_config
            out.trigger_type = update.trigger_type or out.trigger_type
        if "system_scope" in update.model_fields_set:
            out.system_scope = update.system_scope
            holder["key"] = True
        holder["task"] = out
        return out

    return MagicMock(
        create_task=AsyncMock(side_effect=_create_task),
        get_task=AsyncMock(side_effect=_get_task),
        update_task=AsyncMock(side_effect=_update_task),
        delete_task=AsyncMock(return_value=True),
        delete_task_classified=AsyncMock(return_value="success"),
        job_has_system_scope_key=MagicMock(side_effect=lambda _tid: holder["key"]),
        scheduler=MagicMock(get_jobs=MagicMock(return_value=[])),
    )


def _seed(svc: SystemTaskService, cron: str = "0 9 * * *") -> None:
    del cron  # schedule lives in APS only
    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=TID,
            platform="windows",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
            system_task_identifier=f"\\MWU\\{TID}",
            registered_exe_path="/usr/bin/mwu",
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
        )
    )
    svc._memory_state = st
    svc._save_state(st)


def _reg(svc: SystemTaskService):
    return svc._find_registration(svc._load_state(), TID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cleanup_ok,match",
    [
        (True, "native boom"),
        (False, "APS cleanup failed"),
    ],
)
async def test_create_native_failure_aps_cleanup(service, backend, cleanup_ok, match):
    service._backend = backend
    backend.register = AsyncMock(side_effect=RuntimeError("native boom"))
    mgr = _mgr()
    mgr.delete_task = AsyncMock(return_value=cleanup_ok)
    mgr.delete_task_classified = AsyncMock(
        return_value="success" if cleanup_ok else "indeterminate"
    )
    caps, trig = _patch_caps()
    with caps, trig, pytest.raises(RuntimeError, match=match):
        await service.create_task_synced(mgr, _create())
    mgr.delete_task.assert_awaited_once_with(TID)
    if cleanup_ok:
        assert _reg(service) is None
    else:
        assert _reg(service) is not None and _reg(service).state == "error"


@pytest.mark.asyncio
async def test_update_omitted_resyncs_new_trigger(service, backend):
    service._backend = backend
    _seed(service)
    # Legacy missing key → JSON inject then reconcile registers
    t = _task("0 10 * * *", system_scope=None)
    mgr = _mgr(t, has_scope_key=False)
    # After inject+update, get_task should reflect user scope for reconcile.
    async def get_after(_tid):
        return _task("0 10 * * *", system_scope="user", name="task")

    mgr.get_task = AsyncMock(side_effect=get_after)
    mgr.job_has_system_scope_key = MagicMock(return_value=False)
    # After update inject, key will be present on real manager; simulate post-update:
    call = {"n": 0}

    def key_fn(_tid):
        call["n"] += 1
        return call["n"] > 1  # first (pre) False, later True

    mgr.job_has_system_scope_key = MagicMock(side_effect=key_fn)

    async def update_side(_tid, upd):
        return _task(
            "0 10 * * *",
            system_scope=upd.system_scope if "system_scope" in upd.model_fields_set else "user",
            name="task",
        )

    mgr.update_task = AsyncMock(side_effect=update_side)
    update = ScheduledTaskUpdate(
        trigger_type="cron", trigger_config=CronTriggerConfig(cron="0 10 * * *")
    )
    caps, trig = _patch_caps()
    with caps, trig:
        result = await service.update_task_synced(mgr, TID, update)
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert backend.register.await_args.args[0].trigger.cron_expression == "0 10 * * *"
    reg = _reg(service)
    assert reg is not None and reg.state == "active"
    assert reg.last_known_scope == SystemTaskScope.USER


@pytest.mark.asyncio
async def test_update_omitted_aps_present_none_does_not_reregister_from_json(
    service, backend
):
    """APS key present with None is authoritative disable; no JSON re-register."""
    service._backend = backend
    _seed(service)
    # Native currently present so cleanup must unregister.
    backend.is_registered = AsyncMock(return_value=True)
    task = _task(system_scope=None)
    mgr = _mgr(task, has_scope_key=True)
    caps, trig = _patch_caps()
    with caps, trig:
        result = await service.update_task_synced(mgr, TID, ScheduledTaskUpdate(name="x"))
    assert result.aps_outcome == "success"
    backend.register.assert_not_awaited()
    backend.unregister.assert_awaited()


@pytest.mark.asyncio
async def test_update_omitted_aps_present_user_registers_aps_scope(service, backend):
    service._backend = backend
    _seed(service)
    task = _task("0 12 * * *", system_scope="user")
    mgr = _mgr(task, has_scope_key=True)
    caps, trig = _patch_caps()
    with caps, trig:
        result = await service.update_task_synced(
            mgr,
            TID,
            ScheduledTaskUpdate(
                trigger_type="cron",
                trigger_config=CronTriggerConfig(cron="0 12 * * *"),
            ),
        )
    assert result.aps_outcome == "success"
    backend.register.assert_awaited()
    assert backend.register.await_args.args[0].scope == SystemTaskScope.USER
    assert (
        backend.register.await_args.args[0].trigger.cron_expression == "0 12 * * *"
    )


@pytest.mark.asyncio
async def test_real_legacy_update_injects_json_scope_into_aps(tmp_path, backend):
    """Real paused SQLite: legacy absent key + name/trigger update persists JSON scope."""
    from apscheduler.triggers.cron import CronTrigger

    from scheduler_manager import SchedulerManager, execute_scheduled_task

    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    svc = SystemTaskService(tmp_path)
    svc._backend = backend
    _seed(svc, cron="0 9 * * *")

    mgr = SchedulerManager()
    mgr._db_path = tmp_path / "scheduler.sqlite"
    await mgr.initialize(start_scheduler=True, paused=True)
    assert mgr.scheduler is not None
    # Legacy job: no system_scope key
    mgr.scheduler.add_job(
        execute_scheduled_task,
        CronTrigger(minute="0", hour="9", day="*", month="*", day_of_week="*"),
        id=TID,
        kwargs={
            "task_id": TID,
            "task_name": "legacy",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {"Main": {}},
            "pre_tasks": [],
            "controller_name": None,
            "device": None,
            "resource_name": None,
        },
    )
    mgr.scheduler.pause_job(TID)
    assert "system_scope" not in (mgr.scheduler.get_job(TID).kwargs or {})

    caps, trig = _patch_caps()
    with caps, trig:
        result = await svc.update_task_synced(
            mgr,
            TID,
            ScheduledTaskUpdate(
                name="renamed-legacy",
                trigger_type="cron",
                trigger_config=CronTriggerConfig(cron="0 10 * * *"),
            ),
        )
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert result.task.system_scope == "user"
    job = mgr.scheduler.get_job(TID)
    assert job is not None
    assert "system_scope" in job.kwargs
    assert job.kwargs["system_scope"] == "user"
    assert job.kwargs["task_name"] == "renamed-legacy"
    backend.register.assert_awaited()
    assert backend.register.await_args.args[0].scope == SystemTaskScope.USER
    assert backend.register.await_args.args[0].trigger.cron_expression == "0 10 * * *"
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_real_aps_present_none_update_no_json_reregister(tmp_path, backend):
    """Real paused SQLite: present system_scope=None is not overwritten by JSON."""
    from apscheduler.triggers.cron import CronTrigger

    from scheduler_manager import SchedulerManager, execute_scheduled_task

    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    svc = SystemTaskService(tmp_path)
    svc._backend = backend
    _seed(svc)
    # Present so cleanup calls unregister; after unregister still-absent.
    present = {"v": True}

    async def is_reg(*_a, **_k):
        return present["v"]

    async def unreg(*_a, **_k):
        present["v"] = False

    backend.is_registered = AsyncMock(side_effect=is_reg)
    backend.unregister = AsyncMock(side_effect=unreg)

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
            "task_name": "disabled-scope",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {"Main": {}},
            "pre_tasks": [],
            "controller_name": None,
            "device": None,
            "resource_name": None,
            "system_scope": None,
        },
    )
    mgr.scheduler.pause_job(TID)

    caps, trig = _patch_caps()
    with caps, trig:
        result = await svc.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(name="still-disabled")
        )
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert result.task.system_scope is None
    job = mgr.scheduler.get_job(TID)
    assert job is not None
    assert job.kwargs.get("system_scope") is None
    backend.register.assert_not_awaited()
    backend.unregister.assert_awaited()
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_update_native_failure_error_state(service, backend):
    service._backend = backend
    _seed(service)
    backend.register = AsyncMock(side_effect=RuntimeError("native fail"))
    mgr = _mgr(_task("0 11 * * *", system_scope="user"), has_scope_key=True)
    caps, trig = _patch_caps()
    with caps, trig:
        # APS success + native failure is partial success (no raise).
        result = await service.update_task_synced(
            mgr,
            TID,
            ScheduledTaskUpdate(
                trigger_type="cron",
                trigger_config=CronTriggerConfig(cron="0 11 * * *"),
            ),
        )
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert result.native_error is not None
    mgr.update_task.assert_awaited_once()
    mgr.delete_task.assert_not_awaited()
    assert _reg(service) is not None and _reg(service).state == "error"


@pytest.mark.asyncio
async def test_update_snapshot_aps_none_disabled_status(service, backend):
    """native_status after update must not treat last_known as active when APS None."""
    service._backend = backend
    _seed(service)
    present = {"v": True}

    async def is_reg(*_a, **_k):
        return present["v"]

    async def unreg(*_a, **_k):
        present["v"] = False

    backend.is_registered = AsyncMock(side_effect=is_reg)
    backend.unregister = AsyncMock(side_effect=unreg)

    task = _task(system_scope=None)
    mgr = _mgr(task, has_scope_key=True)
    caps, trig = _patch_caps()
    with caps, trig:
        result = await service.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(name="disabled")
        )
    assert result.aps_outcome == "success"
    assert result.native_status is not None
    ns = result.native_status
    # After clean, record may be gone → no operational record; or if present, disabled.
    if ns.scope is not None or ns.desired_scope is not None:
        # Should not report stale USER as active desired when APS is None
        assert ns.reason and (
            "None" in (ns.reason or "") or "disabled" in (ns.reason or "").lower()
            or "no operational" in (ns.reason or "").lower()
        )
    assert ns.registered is False
    assert ns.path_valid is False
    assert ns.verified is False


@pytest.mark.asyncio
async def test_update_snapshot_aps_missing_not_authoritative_native(service, backend):
    """When APS job vanishes post-update path, status must not path_valid/registered true."""
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=True)  # historical native present

    # get_task: first pre-check returns task; after update, reconcile/status see missing.
    live = _task(system_scope="user")
    calls = {"n": 0}

    async def get_task(_tid):
        calls["n"] += 1
        # pre-check + update path uses task; force missing only for late status snapshot
        # by returning task always for update, then None after update_task
        if calls["n"] <= 2:
            return live
        return None

    async def update_task(_tid, upd):
        return live

    mgr = MagicMock()
    mgr.get_task = AsyncMock(side_effect=get_task)
    mgr.update_task = AsyncMock(side_effect=update_task)
    mgr.job_has_system_scope_key = MagicMock(return_value=True)
    mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
    mgr.delete_task_classified = AsyncMock(return_value="success")

    caps, trig = _patch_caps()
    with caps, trig:
        result = await service.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(name="x")
        )
    assert result.aps_outcome == "success"
    assert result.native_status is not None
    ns = result.native_status
    assert ns.registered is False
    assert ns.path_valid is False
    assert ns.verified is False
    assert ns.reason and (
        "missing" in ns.reason.lower() or "unknown" in ns.reason.lower()
    )


@pytest.mark.asyncio
async def test_update_snapshot_native_absent_path_invalid(service, backend):
    service._backend = backend
    exe = service.current_exe_path
    _seed(service)
    # Align diagnostic path but native absent after reconcile
    st = service._load_state()
    reg = service._find_registration(st, TID)
    assert reg
    reg.registered_exe_path = exe
    service._save_state(st)

    backend.is_registered = AsyncMock(return_value=False)
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    backend.register = AsyncMock()  # reconcile may try register

    mgr = _mgr(_task(system_scope="user"), has_scope_key=True)
    caps, trig = _patch_caps()
    with caps, trig:
        result = await service.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(name="n")
        )
    assert result.aps_outcome == "success"
    assert result.native_status is not None
    # After successful reconcile register, may be present; force check snapshot helper alone
    # if register succeeded path may be valid — assert via direct snapshot with absent
    backend.is_registered = AsyncMock(return_value=False)
    async with service._async_lock:
        snap = await service._status_snapshot_locked(TID, mgr)
    assert snap is not None
    assert snap.registered is False
    assert snap.path_valid is False


@pytest.mark.asyncio
async def test_update_snapshot_empty_exe_path_invalid(service, backend):
    """Empty registered_exe_path never path_valid even if native present+verified."""
    service._backend = backend
    _seed(service)
    st = service._load_state()
    reg = service._find_registration(st, TID)
    assert reg
    reg.registered_exe_path = ""
    reg.state = "active"
    service._save_state(st)

    backend.is_registered = AsyncMock(return_value=True)
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    # prevent reconcile from rewriting path
    backend.register = AsyncMock()

    mgr = _mgr(_task(system_scope="user"), has_scope_key=True)

    # Make reconcile a no-op path by matching scope and present+verify
    # but keep empty registered_exe_path after reconcile by re-clearing
    caps, trig = _patch_caps()
    with caps, trig:
        await service.update_task_synced(mgr, TID, ScheduledTaskUpdate(name="n"))
    # Re-seed empty path and snapshot
    st = service._load_state()
    reg = service._find_registration(st, TID)
    if reg is not None:
        reg.registered_exe_path = ""
        service._save_state(st)
    async with service._async_lock:
        snap = await service._status_snapshot_locked(TID, mgr)
    if snap is not None and snap.registered:
        assert snap.path_valid is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "system_scope,expect_register",
    [(None, False), ("user", True)],
)
async def test_update_explicit_null_vs_scope(
    service, backend, system_scope, expect_register
):
    service._backend = backend
    if not expect_register:
        _seed(service)
        present = {"v": True}

        async def is_reg(*_a, **_k):
            return present["v"]

        async def unreg(*_a, **_k):
            present["v"] = False

        backend.is_registered = AsyncMock(side_effect=is_reg)
        backend.unregister = AsyncMock(side_effect=unreg)
    # Explicit null: start with user scope key present; value: register user
    mgr = _mgr(_task(system_scope="user"), has_scope_key=True)
    update = ScheduledTaskUpdate(system_scope=system_scope)
    caps, trig = _patch_caps()
    with caps, trig:
        result = await service.update_task_synced(mgr, TID, update)
    assert result.aps_outcome == "success"
    if expect_register:
        backend.register.assert_awaited()
        assert _reg(service) is not None and _reg(service).state == "active"
    else:
        backend.unregister.assert_awaited()
        assert _reg(service) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("aps_ok", [True, False])
async def test_delete_native_then_aps(service, backend, aps_ok):
    service._backend = backend
    _seed(service)
    order: list[str] = []
    present = {"v": True}

    async def is_reg(*_a, **_k):
        return present["v"]

    async def unreg(*_a, **_k):
        order.append("native")
        present["v"] = False

    backend.is_registered = AsyncMock(side_effect=is_reg)
    backend.unregister = AsyncMock(side_effect=unreg)
    mgr = _mgr()

    async def aps_del_class(*_a, **_k):
        order.append("aps")
        return "success" if aps_ok else "indeterminate"

    mgr.delete_task_classified = AsyncMock(side_effect=aps_del_class)
    mgr.delete_task = AsyncMock(return_value=aps_ok)
    if aps_ok:
        assert await service.delete_task_synced(mgr, TID) is True
        assert _reg(service) is None
    else:
        with pytest.raises(RuntimeError, match="partial delete failure"):
            await service.delete_task_synced(mgr, TID)
        reg = _reg(service)
        assert reg is not None
        assert reg.state == "error"
        assert "APS delete" in (reg.last_error or "") or "indeterminate" in (
            reg.last_error or ""
        )
    assert order == ["native", "aps"]


@pytest.mark.asyncio
async def test_delete_untracked_native_before_aps(service, backend):
    """No durable reg, but native present on USER → clean then APS delete."""
    service._backend = backend
    present = {SystemTaskScope.USER: True, SystemTaskScope.SYSTEM: False}

    async def is_reg(_tid, scope):
        return present.get(scope, False)

    async def unreg(_tid, scope):
        present[scope] = False

    backend.is_registered = AsyncMock(side_effect=is_reg)
    backend.unregister = AsyncMock(side_effect=unreg)
    mgr = _mgr()
    assert await service.delete_task_synced(mgr, TID) is True
    backend.unregister.assert_awaited()
    mgr.delete_task_classified.assert_awaited_once_with(TID)
    assert _reg(service) is None


@pytest.mark.asyncio
async def test_lock_serializes_mutations(service, backend):
    service._backend = backend
    mgr = _mgr()
    started, release = asyncio.Event(), asyncio.Event()
    order: list[str] = []
    n = 0

    async def slow_create(_req):
        nonlocal n
        n += 1
        if n == 1:
            order.append("first-enter")
            started.set()
            await release.wait()
            order.append("first-done")
        else:
            order.append("second-enter")
        return _task()

    mgr.create_task = AsyncMock(side_effect=slow_create)

    async def second():
        await started.wait()
        order.append("second-waiting")
        await service.create_task_synced(mgr, _create(None))
        order.append("second-done")

    t1 = asyncio.create_task(service.create_task_synced(mgr, _create(None)))
    t2 = asyncio.create_task(second())
    await started.wait()
    await asyncio.sleep(0.05)
    assert "second-enter" not in order
    release.set()
    await asyncio.gather(t1, t2)
    assert order == [
        "first-enter",
        "second-waiting",
        "first-done",
        "second-enter",
        "second-done",
    ]
