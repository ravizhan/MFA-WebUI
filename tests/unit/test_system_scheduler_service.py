"""SystemTaskService unit tests — status/persistence + USER-only APS contracts.

External reconcile/repair matrix lives in test_scheduler_reconcile.py.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    CronTriggerConfig,
    SystemTaskOperationalRecord,
    SystemTaskScope,
)
from services.system_scheduler import SystemTaskService, _SystemTaskState

TID = "550e8400-e29b-41d4-a716-446655440000"
RegState = Literal[
    "pending_register", "active", "orphaned", "pending_cleanup", "error"
]


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
    b.build_identifier = MagicMock(side_effect=lambda tid, _s: f"\\MWU\\{tid}")
    return b


def _trig(warnings: list[str] | None = None):
    return patch(
        "services.system_scheduler.validate_trigger_for_platform",
        return_value=list(warnings or []),
    )


def _seed(
    svc: SystemTaskService,
    *,
    state: RegState = "active",
    orphaned: bool = False,
    exe: str = "/usr/bin/mwu",
    last_known: SystemTaskScope = SystemTaskScope.USER,
) -> None:
    op_state = (
        "error"
        if state in ("error", "orphaned", "pending_register", "pending_cleanup")
        or orphaned
        else "active"
    )
    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=TID,
            platform="windows",
            state=op_state,  # type: ignore[arg-type]
            last_known_scope=last_known,
            cleanup_scopes=[last_known],
            system_task_identifier=f"\\MWU\\{TID}",
            registered_exe_path=exe,
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
            last_error="orphaned migration" if orphaned or state == "orphaned" else None,
        )
    )
    svc._memory_state = st
    svc._save_state(st)


class TestStatePersistence:
    def test_load_empty_state(self, service: SystemTaskService):
        state = service._load_state()
        assert state.version == 3
        assert state.records == []

    def test_save_and_load(self, service: SystemTaskService):
        _seed(service)
        service._memory_state = None
        loaded = service._load_state()
        assert len(loaded.records) == 1
        assert loaded.records[0].task_id == TID
        assert loaded.records[0].state == "active"

    def test_load_corrupted_file_fail_closed(self, service: SystemTaskService):
        service._state_file.parent.mkdir(parents=True, exist_ok=True)
        service._state_file.write_text("{ invalid json", encoding="utf-8")
        state = service._load_state()
        assert state.corrupt is True
        with pytest.raises(RuntimeError, match="corrupt"):
            service._save_state(state)


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_unknown_query(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(side_effect=RuntimeError("schtasks boom"))
        from models.scheduler import ScheduledTask

        task = ScheduledTask(
            id=TID,
            name="task",
            enabled=True,
            trigger_type="cron",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            task_list=["Main"],
            system_scope="user",
        )
        mgr = MagicMock()
        mgr.get_task = AsyncMock(return_value=task)
        status = await service.get_status(TID, manager=mgr)
        assert status.observed
        assert any("unknown" in (o.details or "").lower() for o in status.observed)

    @pytest.mark.asyncio
    async def test_get_status_not_registered(self, service, mock_backend):
        service._backend = mock_backend
        status = await service.get_status(TID)
        assert status.registered is False

    @pytest.mark.asyncio
    async def test_get_status_legacy_system_scope_reads_as_user_wakeup(
        self, service, mock_backend
    ):
        """APS system_scope=system is user wakeup; status scope is USER."""
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=True)
        from models.scheduler import ScheduledTask

        task = ScheduledTask(
            id=TID,
            name="task",
            enabled=True,
            trigger_type="cron",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            task_list=["Main"],
            system_scope="system",  # legacy
        )
        mgr = MagicMock()
        mgr.get_task = AsyncMock(return_value=task)
        with _trig():
            status = await service.get_status(TID, manager=mgr)
        assert status.scope == SystemTaskScope.USER
        assert status.desired_scope == SystemTaskScope.USER
        assert status.enabled is True


def _mgr_for_repair(
    *,
    name: str = "task",
    cron: str = "0 9 * * *",
    scope: str | None = "user",
    missing: bool = False,
    decode_error: bool = False,
):
    from models.scheduler import ScheduledTask
    from scheduler_job_codec import SchedulerJobDecodeError

    mgr = MagicMock()
    mgr.job_has_system_scope_key = MagicMock(return_value=True)
    if decode_error:

        async def boom(_tid):
            raise SchedulerJobDecodeError("bad trigger", job_id=_tid)

        mgr.get_task = AsyncMock(side_effect=boom)
        return mgr
    if missing:
        mgr.get_task = AsyncMock(return_value=None)
        return mgr
    task = ScheduledTask(
        id=TID,
        name=name,
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
        system_scope=scope,  # type: ignore[arg-type]
    )
    mgr.get_task = AsyncMock(return_value=task)
    return mgr


class TestRepairServiceContracts:
    """Service-layer contracts not covered by reconcile matrix."""

    @pytest.mark.asyncio
    async def test_repair_requires_manager(self, service, mock_backend):
        service._backend = mock_backend
        with pytest.raises(ValueError, match="requires SchedulerManager"):
            await service.repair_all()

    @pytest.mark.asyncio
    async def test_repair_aps_system_scope_registers_user_only(
        self, service, mock_backend
    ):
        """Legacy APS system_scope=system still registers USER native wakeup."""
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        with _trig():
            await service.repair_all(
                _mgr_for_repair(name="from-aps", cron="0 8 * * *", scope="system")
            )
        mock_backend.register.assert_awaited()
        spec = mock_backend.register.await_args.args[0]
        assert spec.task_name == "from-aps"
        assert spec.scope == SystemTaskScope.USER
        assert spec.trigger.cron_expression == "0 8 * * *"

    @pytest.mark.asyncio
    async def test_repair_historical_system_cleanup_then_user_register(
        self, service, mock_backend
    ):
        """last_known SYSTEM cleaned (no elevation) before USER register."""
        service._backend = mock_backend
        _seed(service, last_known=SystemTaskScope.SYSTEM)
        order: list[str] = []
        present = {SystemTaskScope.USER: False, SystemTaskScope.SYSTEM: True}

        async def unreg(tid, scope):
            order.append(f"unreg:{scope.value}")
            present[scope] = False

        async def is_reg(tid, scope):
            order.append(f"is_reg:{scope.value}")
            return present.get(scope, False)

        async def reg(spec):
            order.append(f"reg:{spec.scope.value}")
            present[spec.scope] = True

        mock_backend.unregister = AsyncMock(side_effect=unreg)
        mock_backend.is_registered = AsyncMock(side_effect=is_reg)
        mock_backend.register = AsyncMock(side_effect=reg)
        mock_backend.verify_registration = AsyncMock(return_value=(True, "ok"))

        with _trig():
            result = await service.repair_all(
                _mgr_for_repair(name="aps-name", cron="0 8 * * *", scope="user")
            )
        assert result["repaired"] == 1
        assert order.index("unreg:system") < order.index("reg:user")
        st = service._find_registration(service._load_state(), TID)
        assert st is not None
        assert st.state == "active"
        assert st.last_known_scope == SystemTaskScope.USER
        assert st.observed and st.observed[0].scope == SystemTaskScope.USER

    @pytest.mark.asyncio
    async def test_repair_converges_stale_warnings(self, service, mock_backend):
        """Successful repair replaces stale warnings with trigger validation warnings."""
        service._backend = mock_backend
        _seed(service)
        st = service._load_state()
        reg = service._find_registration(st, TID)
        assert reg is not None
        reg.warnings = ["stale warning from prior registration", "obsolete"]
        service._save_state(st)

        mock_backend.is_registered = AsyncMock(return_value=False)
        mock_backend.register = AsyncMock()
        mock_backend.verify_registration = AsyncMock(return_value=(True, "ok"))

        expected = ["fresh-trigger-warning"]
        with _trig(expected):
            result = await service.repair_all(
                _mgr_for_repair(name="n", cron="0 9 * * *", scope="user")
            )
        assert result["repaired"] == 1
        reg2 = service._find_registration(service._load_state(), TID)
        assert reg2 is not None
        assert reg2.warnings == expected
        assert "stale warning from prior registration" not in reg2.warnings

        mock_backend.register.reset_mock()
        mock_backend.is_registered = AsyncMock(return_value=True)
        with _trig(expected):
            result2 = await service.repair_all(
                _mgr_for_repair(name="n", cron="0 9 * * *", scope="user")
            )
        assert result2["repaired"] == 0
        mock_backend.register.assert_not_awaited()
        reg3 = service._find_registration(service._load_state(), TID)
        assert reg3 is not None
        assert reg3.warnings == expected
