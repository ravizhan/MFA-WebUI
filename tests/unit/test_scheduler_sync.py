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
    OSTriggerSpec,
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    SystemTaskRegistration,
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


def _task(cron: str = "0 9 * * *") -> ScheduledTask:
    return ScheduledTask(
        id=TID,
        name="task",
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
    )


def _create(scope: Literal["user", "system"] | None = "user") -> ScheduledTaskCreate:
    return ScheduledTaskCreate(
        name="task",
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        system_scope=scope,
    )


def _mgr(task: ScheduledTask | None = None) -> MagicMock:
    t = task or _task()
    return MagicMock(
        create_task=AsyncMock(return_value=t),
        get_task=AsyncMock(return_value=t),
        update_task=AsyncMock(return_value=t),
        delete_task=AsyncMock(return_value=True),
    )


def _seed(svc: SystemTaskService, cron: str = "0 9 * * *") -> None:
    st = _SystemTaskState()
    st.registrations.append(
        SystemTaskRegistration(
            task_id=TID,
            task_name="task",
            platform="windows",
            desired_scope=SystemTaskScope.USER,
            desired_trigger=OSTriggerSpec(trigger_type="cron", cron_expression=cron),
            desired_exe_path="/usr/bin/mwu",
            system_task_identifier=f"\\MWU\\{TID}",
            registered_exe_path="/usr/bin/mwu",
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
            state="active",
        )
    )
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
    mgr = _mgr(_task("0 10 * * *"))
    update = ScheduledTaskUpdate(
        trigger_type="cron", trigger_config=CronTriggerConfig(cron="0 10 * * *")
    )
    caps, trig = _patch_caps()
    with caps, trig:
        await service.update_task_synced(mgr, TID, update)
    assert backend.register.await_args.args[0].trigger.cron_expression == "0 10 * * *"
    reg = _reg(service)
    assert reg is not None and reg.state == "active"
    assert reg.desired_trigger.cron_expression == "0 10 * * *"


@pytest.mark.asyncio
async def test_update_native_failure_error_state(service, backend):
    service._backend = backend
    _seed(service)
    backend.register = AsyncMock(side_effect=RuntimeError("native fail"))
    mgr = _mgr(_task("0 11 * * *"))
    caps, trig = _patch_caps()
    with caps, trig:
        with pytest.raises(RuntimeError, match="native fail"):
            await service.update_task_synced(
                mgr,
                TID,
                ScheduledTaskUpdate(
                    trigger_type="cron",
                    trigger_config=CronTriggerConfig(cron="0 11 * * *"),
                ),
            )
    mgr.update_task.assert_awaited_once()
    mgr.delete_task.assert_not_awaited()
    assert _reg(service) is not None and _reg(service).state == "error"


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
    mgr = _mgr()
    update = ScheduledTaskUpdate(system_scope=system_scope)
    caps, trig = _patch_caps()
    with caps, trig:
        await service.update_task_synced(mgr, TID, update)
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
    backend.unregister = AsyncMock(side_effect=lambda *_a, **_k: order.append("native"))
    mgr = _mgr()

    async def aps_del(*_a, **_k):
        order.append("aps")
        return aps_ok

    mgr.delete_task = AsyncMock(side_effect=aps_del)
    if aps_ok:
        assert await service.delete_task_synced(mgr, TID) is True
        assert _reg(service) is None
    else:
        with pytest.raises(RuntimeError, match="partial delete failure"):
            await service.delete_task_synced(mgr, TID)
        reg = _reg(service)
        assert reg is not None
        assert reg.state == "error"
        assert reg.pending_operation == "repair"
        assert "APS delete" in (reg.last_error or "")
        assert any(not o.present for o in reg.observed)
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
    mgr.delete_task.assert_awaited_once_with(TID)
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
