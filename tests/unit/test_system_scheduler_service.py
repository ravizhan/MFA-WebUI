"""SystemTaskService unit tests — status/persistence + repair_all entry contracts.

Unique reconcile_task scenarios (stale path, decode errors, delete durability)
live in test_scheduler_reconcile.py; APS+native sync wrappers in test_scheduler_sync.py.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    OPERATIONAL_STATE_VERSION,
    CronTriggerConfig,
    ScheduledTask,
    SystemTaskOperationalRecord,
)
from services.system_scheduler import SystemTaskService, _SystemTaskState

TID = "550e8400-e29b-41d4-a716-446655440000"
OpState = Literal["active", "error"]


@pytest.fixture
def service(tmp_path: Path) -> SystemTaskService:
    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    return SystemTaskService(tmp_path)


@pytest.fixture
def mock_backend():
    b = MagicMock()
    b.platform_name = "windows"
    b.register = AsyncMock()
    b.unregister = AsyncMock()
    b.is_registered = AsyncMock(return_value=False)
    b.verify_registration = AsyncMock(return_value=(True, "ok"))
    b.build_identifier = MagicMock(side_effect=lambda tid: f"\\MWU\\{tid}")
    return b


def _trig(warnings: list[str] | None = None):
    return patch(
        "services.system_scheduler.validate_trigger_for_platform",
        return_value=list(warnings or []),
    )


def _seed(
    svc: SystemTaskService,
    *,
    state: OpState = "active",
    exe: str = "/usr/bin/mwu",
) -> None:
    st = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=TID,
            platform="windows",
            state=state,
            registered_exe_path=exe,
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
            last_error="boom" if state == "error" else None,
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


def _mgr(
    *,
    name: str = "task",
    cron: str = "0 9 * * *",
    wakeup_enabled: bool = True,
    missing: bool = False,
    decode_error: bool = False,
):
    from scheduler_job_codec import SchedulerJobDecodeError

    mgr = MagicMock()
    if decode_error:

        async def boom(_tid):
            raise SchedulerJobDecodeError("bad trigger", job_id=_tid)

        mgr.get_task = AsyncMock(side_effect=boom)
        return mgr
    if missing:
        mgr.get_task = AsyncMock(return_value=None)
        return mgr
    mgr.get_task = AsyncMock(
        return_value=_aps_task(name=name, cron=cron, wakeup_enabled=wakeup_enabled)
    )
    return mgr


class TestStatePersistence:
    def test_load_empty_state(self, service: SystemTaskService):
        state = service._load_state()
        assert state.version == OPERATIONAL_STATE_VERSION
        assert state.records == []


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_unknown_query(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(side_effect=RuntimeError("schtasks boom"))
        mgr = MagicMock()
        mgr.get_task = AsyncMock(return_value=_aps_task())
        status = await service.get_status(TID, manager=mgr)
        assert status.registered is False
        assert status.reason and "unknown" in status.reason.lower()

    @pytest.mark.asyncio
    async def test_get_status_not_registered(self, service, mock_backend):
        service._backend = mock_backend
        status = await service.get_status(TID)
        assert status.registered is False
        assert status.reason and "no operational record" in status.reason

    @pytest.mark.asyncio
    async def test_get_status_wakeup_enabled_registers_view(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=True)
        mgr = MagicMock()
        mgr.get_task = AsyncMock(return_value=_aps_task())
        with _trig():
            status = await service.get_status(TID, manager=mgr)
        assert status.enabled is True
        assert status.registered is True


class TestRepairServiceContracts:
    """Service-layer contracts not covered by reconcile matrix."""

    @pytest.mark.asyncio
    async def test_repair_requires_manager(self, service, mock_backend):
        service._backend = mock_backend
        with pytest.raises(ValueError, match="requires SchedulerManager"):
            await service.repair_all()

    @pytest.mark.asyncio
    async def test_repair_wakeup_enabled_registers(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        mgr = _mgr(name="from-aps", cron="0 8 * * *", wakeup_enabled=True)
        with _trig():
            await service.repair_all(mgr)
        mock_backend.register.assert_awaited()
        spec = mock_backend.register.await_args.args[0]
        assert spec.task_name == "from-aps"
        assert not hasattr(spec, "scope") or "scope" not in getattr(
            spec, "model_fields", {}
        )
        assert spec.trigger.cron_expression == "0 8 * * *"

        # Second repair after convergence reports zero repairs.
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.verify_registration = AsyncMock(return_value=(True, "ok"))
        mock_backend.register.reset_mock()
        with _trig():
            result = await service.repair_all(mgr)
        assert result["repaired"] == 0
        mock_backend.register.assert_not_awaited()
