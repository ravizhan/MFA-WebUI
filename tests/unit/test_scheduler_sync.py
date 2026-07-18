"""Focused APS+native sync wrapper tests (wakeup_enabled)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    OPERATIONAL_STATE_VERSION,
    CronTriggerConfig,
    ReconcileTaskResult,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemTaskOperationalRecord,
)
from scheduler_job_codec import SchedulerJobDecodeError
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
        build_identifier=MagicMock(side_effect=lambda tid: f"\\MWU\\{tid}"),
    )


def _patch_trig():
    return patch(
        "services.system_scheduler.validate_trigger_for_platform", return_value=[]
    )


def _task(
    cron: str = "0 9 * * *",
    *,
    wakeup_enabled: bool = False,
    name: str = "task",
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


def _create(*, wakeup_enabled: bool = True) -> ScheduledTaskCreate:
    return ScheduledTaskCreate(
        name="task",
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        wakeup_enabled=wakeup_enabled,
    )


def _mgr(task: ScheduledTask | None = None) -> MagicMock:
    t = task or _task(wakeup_enabled=True)
    holder: dict[str, object] = {"task": t.model_copy(deep=True)}

    async def _create_task(create: ScheduledTaskCreate):
        cur = holder["task"]
        assert isinstance(cur, ScheduledTask)
        out = cur.model_copy(deep=True)
        out.wakeup_enabled = create.wakeup_enabled
        out.name = create.name
        holder["task"] = out
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
        if "wakeup_enabled" in update.model_fields_set:
            out.wakeup_enabled = bool(update.wakeup_enabled)
        holder["task"] = out
        return out

    return MagicMock(
        create_task=AsyncMock(side_effect=_create_task),
        get_task=AsyncMock(side_effect=_get_task),
        update_task=AsyncMock(side_effect=_update_task),
        delete_task=AsyncMock(return_value=True),
        delete_task_classified=AsyncMock(return_value="success"),
        scheduler=MagicMock(get_jobs=MagicMock(return_value=[])),
    )


def _seed(svc: SystemTaskService) -> None:
    st = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=TID,
            platform="windows",
            state="active",
            registered_exe_path="/usr/bin/mwu",
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
        )
    )
    svc._memory_state = st
    svc._save_state(st)


def _reg(svc: SystemTaskService):
    return svc._find_record(svc._load_state(), TID)


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
    with _patch_trig(), pytest.raises(RuntimeError, match=match):
        await service.create_task_synced(mgr, _create(wakeup_enabled=True))
    mgr.delete_task.assert_awaited_once_with(TID)
    if cleanup_ok:
        assert _reg(service) is None
    else:
        assert _reg(service) is not None and _reg(service).state == "error"


@pytest.mark.asyncio
async def test_create_wakeup_false_skips_native(service, backend):
    service._backend = backend
    mgr = _mgr(_task(wakeup_enabled=False))
    task = await service.create_task_synced(mgr, _create(wakeup_enabled=False))
    assert task.wakeup_enabled is False
    backend.register.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_omitted_resyncs_new_trigger(service, backend):
    service._backend = backend
    _seed(service)
    t = _task("0 10 * * *", wakeup_enabled=True)
    mgr = _mgr(t)

    async def update_side(_tid, upd):
        return _task(
            "0 10 * * *",
            wakeup_enabled=True,
            name="task",
        )

    mgr.update_task = AsyncMock(side_effect=update_side)
    update = ScheduledTaskUpdate(
        trigger_type="cron", trigger_config=CronTriggerConfig(cron="0 10 * * *")
    )
    with _patch_trig():
        result = await service.update_task_synced(mgr, TID, update)
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert backend.register.await_args.args[0].trigger.cron_expression == "0 10 * * *"
    reg = _reg(service)
    assert reg is not None and reg.state == "active"


@pytest.mark.asyncio
async def test_real_wakeup_false_update_no_reregister(tmp_path, backend):
    """Real paused SQLite: wakeup_enabled=false is not re-registered."""
    from apscheduler.triggers.cron import CronTrigger

    from scheduler_manager import SchedulerManager, execute_scheduled_task

    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    svc = SystemTaskService(tmp_path)
    svc._backend = backend
    _seed(svc)
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
            "task_name": "disabled-wakeup",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {"Main": {}},
            "pre_tasks": [],
            "controller_name": None,
            "device": None,
            "resource_name": None,
            "wakeup_enabled": False,
        },
    )
    mgr.scheduler.pause_job(TID)

    with _patch_trig():
        result = await svc.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(name="still-disabled")
        )
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert result.task.wakeup_enabled is False
    job = mgr.scheduler.get_job(TID)
    assert job is not None
    assert job.kwargs.get("wakeup_enabled") is False
    backend.register.assert_not_awaited()
    backend.unregister.assert_awaited()
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_real_wakeup_true_update_persists(tmp_path, backend):
    """Real paused SQLite: name/trigger update keeps wakeup_enabled and registers."""
    from apscheduler.triggers.cron import CronTrigger

    from scheduler_manager import SchedulerManager, execute_scheduled_task

    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    svc = SystemTaskService(tmp_path)
    svc._backend = backend
    _seed(svc)

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
            "task_name": "live",
            "task_description": "",
            "task_list": ["Main"],
            "task_options": {"Main": {}},
            "pre_tasks": [],
            "controller_name": None,
            "device": None,
            "resource_name": None,
            "wakeup_enabled": True,
        },
    )
    mgr.scheduler.pause_job(TID)

    with _patch_trig():
        result = await svc.update_task_synced(
            mgr,
            TID,
            ScheduledTaskUpdate(
                name="renamed",
                trigger_type="cron",
                trigger_config=CronTriggerConfig(cron="0 10 * * *"),
            ),
        )
    assert result.aps_outcome == "success"
    assert result.task is not None
    assert result.task.wakeup_enabled is True
    job = mgr.scheduler.get_job(TID)
    assert job is not None
    assert job.kwargs["wakeup_enabled"] is True
    assert job.kwargs["task_name"] == "renamed"
    backend.register.assert_awaited()
    assert backend.register.await_args.args[0].trigger.cron_expression == "0 10 * * *"
    await mgr.shutdown()


@pytest.mark.asyncio
async def test_update_native_failure_error_state(service, backend):
    service._backend = backend
    _seed(service)
    backend.register = AsyncMock(side_effect=RuntimeError("native fail"))
    mgr = _mgr(_task("0 11 * * *", wakeup_enabled=True))
    with _patch_trig():
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
async def test_update_snapshot_wakeup_false_disabled_status(service, backend):
    service._backend = backend
    _seed(service)
    present = {"v": True}

    async def is_reg(*_a, **_k):
        return present["v"]

    async def unreg(*_a, **_k):
        present["v"] = False

    backend.is_registered = AsyncMock(side_effect=is_reg)
    backend.unregister = AsyncMock(side_effect=unreg)

    task = _task(wakeup_enabled=True)
    mgr = _mgr(task)
    with _patch_trig():
        result = await service.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(wakeup_enabled=False)
        )
    assert result.aps_outcome == "success"
    assert result.native_status is not None
    ns = result.native_status
    assert ns.registered is False
    assert ns.path_valid is False
    assert ns.verified is False


@pytest.mark.asyncio
async def test_update_snapshot_aps_missing_not_authoritative_native(service, backend):
    service._backend = backend
    _seed(service)
    backend.is_registered = AsyncMock(return_value=True)

    live = _task(wakeup_enabled=True)
    calls = {"n": 0}

    async def get_task(_tid):
        calls["n"] += 1
        if calls["n"] <= 2:
            return live
        return None

    async def update_task(_tid, upd):
        return live

    mgr = MagicMock()
    mgr.get_task = AsyncMock(side_effect=get_task)
    mgr.update_task = AsyncMock(side_effect=update_task)
    mgr.scheduler = MagicMock(get_jobs=MagicMock(return_value=[]))
    mgr.delete_task_classified = AsyncMock(return_value="success")

    with _patch_trig():
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
async def test_update_snapshot_empty_exe_path_invalid(service, backend):
    """Empty registered_exe_path never path_valid even if native present+verified."""
    service._backend = backend
    _seed(service)
    st = service._load_state()
    reg = service._find_record(st, TID)
    assert reg
    reg.registered_exe_path = ""
    reg.state = "active"
    service._save_state(st)

    backend.is_registered = AsyncMock(return_value=True)
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    backend.register = AsyncMock()

    mgr = _mgr(_task(wakeup_enabled=True))
    with _patch_trig():
        await service.update_task_synced(mgr, TID, ScheduledTaskUpdate(name="n"))
    st = service._load_state()
    reg = service._find_record(st, TID)
    if reg is not None:
        reg.registered_exe_path = ""
        service._save_state(st)
    async with service._async_lock:
        snap = await service._status_snapshot_locked(TID, mgr)
    if snap is not None and snap.registered:
        assert snap.path_valid is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wakeup_enabled,expect_register",
    [(False, False), (True, True)],
)
async def test_update_explicit_wakeup(
    service, backend, wakeup_enabled, expect_register
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
    mgr = _mgr(_task(wakeup_enabled=True))
    update = ScheduledTaskUpdate(wakeup_enabled=wakeup_enabled)
    with _patch_trig():
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
    """No durable reg, but native present → clean then APS delete."""
    service._backend = backend
    present = {"v": True}

    async def is_reg(_tid):
        return present["v"]

    async def unreg(_tid):
        present["v"] = False

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
    mgr = _mgr(_task(wakeup_enabled=False))
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
        return _task(wakeup_enabled=False)

    mgr.create_task = AsyncMock(side_effect=slow_create)

    async def second():
        await started.wait()
        order.append("second-waiting")
        await service.create_task_synced(mgr, _create(wakeup_enabled=False))
        order.append("second-done")

    t1 = asyncio.create_task(
        service.create_task_synced(mgr, _create(wakeup_enabled=False))
    )
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


# ---------------------------------------------------------------------------
# Characterization: create compensation / update outcomes / delete restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_compensation_unknown_native_keeps_aps_and_error_record(
    service, backend
):
    """Native cleanup unconfirmed: keep APS job, write error on existing record."""
    service._backend = backend
    _seed(service)
    mgr = _mgr()
    err_result = ReconcileTaskResult(
        task_id=TID,
        action="error",
        detail="native boom",
        native_error="native boom",
    )
    with (
        _patch_trig(),
        patch.object(
            service, "_reconcile_task_locked", new=AsyncMock(return_value=err_result)
        ),
        patch.object(
            service,
            "_ensure_absent",
            new=AsyncMock(return_value=(False, "cleanup not confirmed")),
        ),
        pytest.raises(RuntimeError, match="cleanup could not be verified"),
    ):
        await service.create_task_synced(mgr, _create(wakeup_enabled=True))
    mgr.delete_task.assert_not_awaited()
    reg = _reg(service)
    assert reg is not None
    assert reg.state == "error"
    assert "cleanup not confirmed" in (reg.last_error or "")


@pytest.mark.asyncio
async def test_create_compensation_delete_task_raises_chains_exception(
    service, backend
):
    """APS delete_task raises after native absence: chain cause; no record remove."""
    service._backend = backend
    _seed(service)
    mgr = _mgr()
    aps_err = RuntimeError("aps delete boom")
    mgr.delete_task = AsyncMock(side_effect=aps_err)
    err_result = ReconcileTaskResult(
        task_id=TID,
        action="error",
        detail="native boom",
        native_error="native boom",
    )
    with (
        _patch_trig(),
        patch.object(
            service, "_reconcile_task_locked", new=AsyncMock(return_value=err_result)
        ),
        patch.object(
            service, "_ensure_absent", new=AsyncMock(return_value=(True, None))
        ),
        pytest.raises(RuntimeError, match="APS cleanup failed") as ei,
    ):
        await service.create_task_synced(mgr, _create(wakeup_enabled=True))
    assert ei.value.__cause__ is aps_err
    mgr.delete_task.assert_awaited_once_with(TID)
    # Current behavior: record is only removed after delete_task succeeds.
    reg = _reg(service)
    assert reg is not None
    assert reg.state == "active"


@pytest.mark.asyncio
async def test_update_pre_read_decode_failure_returns_error_outcome(service, backend):
    service._backend = backend
    mgr = _mgr()
    mgr.get_task = AsyncMock(
        side_effect=SchedulerJobDecodeError("bad trigger", job_id=TID)
    )
    result = await service.update_task_synced(
        mgr, TID, ScheduledTaskUpdate(name="x")
    )
    assert result.aps_outcome == "error"
    assert result.task is None
    assert result.aps_error is not None
    assert "decode failed before update" in result.aps_error
    mgr.update_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_mutation_decode_failure_returns_error_outcome(service, backend):
    service._backend = backend
    mgr = _mgr(_task(wakeup_enabled=True))
    mgr.update_task = AsyncMock(
        side_effect=SchedulerJobDecodeError("bad after update", job_id=TID)
    )
    with patch.object(
        service, "_reconcile_task_locked", new=AsyncMock()
    ) as reconcile:
        result = await service.update_task_synced(
            mgr, TID, ScheduledTaskUpdate(name="x")
        )
    assert result.aps_outcome == "error"
    assert result.task is None
    assert result.aps_error is not None
    assert "APS update decode failed" in result.aps_error
    reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_returns_none_aps_absent_returns_not_found(service, backend):
    service._backend = backend
    mgr = _mgr(_task(wakeup_enabled=True))
    mgr.update_task = AsyncMock(return_value=None)
    mgr.scheduler.get_job = MagicMock(return_value=None)
    result = await service.update_task_synced(
        mgr, TID, ScheduledTaskUpdate(name="x")
    )
    assert result.aps_outcome == "not_found"
    assert result.task is None


@pytest.mark.asyncio
async def test_update_returns_none_aps_still_present_returns_error(service, backend):
    service._backend = backend
    mgr = _mgr(_task(wakeup_enabled=True))
    mgr.update_task = AsyncMock(return_value=None)
    mgr.scheduler.get_job = MagicMock(return_value=MagicMock())
    result = await service.update_task_synced(
        mgr, TID, ScheduledTaskUpdate(name="x")
    )
    assert result.aps_outcome == "error"
    assert result.task is None
    assert result.aps_error == "APS update returned None with job still present"


@pytest.mark.asyncio
async def test_delete_pre_failure_restores_prior_record_as_error(service, backend):
    service._backend = backend
    _seed(service)
    prior = _reg(service)
    assert prior is not None
    prior_state = prior.state
    prior_path = prior.registered_exe_path
    prior_at = prior.last_registered_at

    mgr = _mgr()
    mgr.delete_task_classified = AsyncMock(return_value="pre_failure")
    with pytest.raises(RuntimeError, match="partial delete failure"):
        await service.delete_task_synced(mgr, TID)

    reg = _reg(service)
    assert reg is not None
    assert reg.state == "error"
    assert reg.last_error == "APS delete pre_failure after native cleanup"
    # Restored from deep-copied prior (not removed)
    assert reg.registered_exe_path == prior_path
    assert reg.last_registered_at == prior_at
    assert prior_state == "active"
