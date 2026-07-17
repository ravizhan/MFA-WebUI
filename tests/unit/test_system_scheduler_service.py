"""SystemTaskService unit tests — core native repair/status only."""

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
    b.get_next_run_time = AsyncMock(return_value=None)
    b.list_registered = AsyncMock(return_value=[])
    b.verify_registration = AsyncMock(return_value=(True, "ok"))
    b.build_identifier = MagicMock(side_effect=lambda tid, _s: f"\\MWU\\{tid}")
    return b


def _caps(ok: bool = True, reason: str = "enabled"):
    return patch(
        "services.system_scheduler.is_capability_enabled",
        return_value=(ok, reason if ok else reason, []),
    )


def _trig():
    return patch(
        "services.system_scheduler.validate_trigger_for_platform", return_value=[]
    )


def _seed(
    svc: SystemTaskService,
    *,
    state: RegState = "active",
    orphaned: bool = False,
    exe: str = "/usr/bin/mwu",
) -> None:
    op_state = "error" if state in ("error", "orphaned", "pending_register", "pending_cleanup") or orphaned else "active"
    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=TID,
            platform="windows",
            state=op_state,  # type: ignore[arg-type]
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
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
        from models.scheduler import CronTriggerConfig, ScheduledTask
        from unittest.mock import AsyncMock as AM

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
        mgr.get_task = AM(return_value=task)
        status = await service.get_status(TID, manager=mgr)
        assert status.observed
        assert any("unknown" in (o.details or "").lower() for o in status.observed)

    @pytest.mark.asyncio
    async def test_get_status_not_registered(self, service, mock_backend):
        service._backend = mock_backend
        status = await service.get_status(TID)
        assert status.registered is False


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


class TestRepair:
    @pytest.mark.asyncio
    async def test_repair_requires_manager(self, service, mock_backend):
        service._backend = mock_backend
        with pytest.raises(ValueError, match="requires SchedulerManager"):
            await service.repair_all()

    @pytest.mark.asyncio
    async def test_repair_success_missing_native(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        with _caps(), _trig():
            result = await service.repair_all(_mgr_for_repair())
        assert result["repaired"] == 1
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "active"
        mock_backend.register.assert_awaited()
        spec = mock_backend.register.await_args.args[0]
        assert spec.task_name == "task"
        assert spec.scope == SystemTaskScope.USER
        assert spec.trigger.cron_expression == "0 9 * * *"

    @pytest.mark.asyncio
    async def test_repair_uses_aps_name_trigger_scope(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        with _caps(), _trig():
            await service.repair_all(
                _mgr_for_repair(name="from-aps", cron="0 8 * * *", scope="system")
            )
        spec = mock_backend.register.await_args.args[0]
        assert spec.task_name == "from-aps"
        assert spec.scope == SystemTaskScope.SYSTEM
        assert spec.trigger.cron_expression == "0 8 * * *"

    @pytest.mark.asyncio
    async def test_repair_missing_aps_orphan_cleanup(self, service, mock_backend):
        """Missing APS cleans native and removes operational record."""
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        result = await service.repair_all(_mgr_for_repair(missing=True))
        assert result["repaired"] == 1
        mock_backend.register.assert_not_awaited()
        reg = service._find_registration(service._load_state(), TID)
        assert reg is None

    @pytest.mark.asyncio
    async def test_repair_corrupt_aps_no_register(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        result = await service.repair_all(_mgr_for_repair(decode_error=True))
        assert result["failed"] == 1
        mock_backend.register.assert_not_awaited()
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "error"
        assert "decode" in (reg.last_error or "").lower()

    @pytest.mark.asyncio
    async def test_repair_failure_persists_error(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        mock_backend.register = AsyncMock(side_effect=RuntimeError("repair boom"))
        with _caps(), _trig():
            result = await service.repair_all(_mgr_for_repair())
        assert result["failed"] == 1
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "error"
        assert reg.last_error
        mock_backend.unregister.assert_awaited()

    @pytest.mark.asyncio
    async def test_orphan_state_is_reconciled(self, service, mock_backend):
        """Orphaned records are cleaned, not skipped."""
        service._backend = mock_backend
        _seed(service, state="orphaned", orphaned=True)
        mock_backend.is_registered = AsyncMock(return_value=False)
        with _caps(), _trig():
            result = await service.repair_all(_mgr_for_repair())
        assert result["repaired"] >= 1
        mock_backend.register.assert_awaited()

    @pytest.mark.asyncio
    async def test_repair_scope_drift_unregisters_old_before_new(
        self, service, mock_backend
    ):
        """USER→SYSTEM: old unregister + absence check before register; mirrors sync."""
        service._backend = mock_backend
        _seed(service)  # desired_scope USER
        order: list[str] = []
        present = {SystemTaskScope.USER: True, SystemTaskScope.SYSTEM: False}

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

        with _caps(), _trig():
            result = await service.repair_all(
                _mgr_for_repair(name="aps-name", cron="0 8 * * *", scope="system")
            )
        assert result["repaired"] == 1
        assert order.index("unreg:user") < order.index("reg:system")
        assert "is_reg:user" in order
        assert order.index("is_reg:user") < order.index("reg:system")

        st = service._find_registration(service._load_state(), TID)
        assert st is not None
        assert st.state == "active"
        assert st.last_known_scope == SystemTaskScope.SYSTEM
        assert SystemTaskScope.SYSTEM in st.cleanup_scopes
        assert SystemTaskScope.USER in st.cleanup_scopes  # retained for cleanup history
        assert st.last_error is None
        assert st.observed and st.observed[0].scope == SystemTaskScope.SYSTEM

        mock_backend.register.reset_mock()
        mock_backend.unregister.reset_mock()
        mock_backend.is_registered = AsyncMock(return_value=True)
        with _caps(), _trig():
            result2 = await service.repair_all(
                _mgr_for_repair(name="aps-name", cron="0 8 * * *", scope="system")
            )
        assert result2["repaired"] == 0
        mock_backend.register.assert_not_awaited()
        mock_backend.unregister.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_repair_scope_drift_old_still_present_no_new_register(
        self, service, mock_backend
    ):
        service._backend = mock_backend
        _seed(service)
        mock_backend.unregister = AsyncMock()
        # USER always present (old still present after unreg)
        mock_backend.is_registered = AsyncMock(return_value=True)
        with _caps(), _trig():
            result = await service.repair_all(_mgr_for_repair(scope="system"))
        assert result["failed"] == 1
        mock_backend.register.assert_not_awaited()
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "error"
        assert "still present" in (reg.last_error or "")

    @pytest.mark.asyncio
    async def test_repair_scope_drift_old_query_unknown_no_new_register(
        self, service, mock_backend
    ):
        service._backend = mock_backend
        _seed(service)
        mock_backend.unregister = AsyncMock()
        # First is for SYSTEM (new) may be False; then USER cleanup query unknown
        calls = {"n": 0}

        async def is_reg(tid, scope):
            calls["n"] += 1
            if scope == SystemTaskScope.USER:
                if calls["n"] == 1:
                    return True  # present → will unreg
                raise RuntimeError("schtasks unknown")
            return False  # SYSTEM absent

        mock_backend.is_registered = AsyncMock(side_effect=is_reg)
        with _caps(), _trig():
            result = await service.repair_all(_mgr_for_repair(scope="system"))
        assert result["failed"] == 1
        mock_backend.register.assert_not_awaited()
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "error"
        assert "unknown" in (reg.last_error or "").lower()

    @pytest.mark.asyncio
    async def test_repair_converges_stale_warnings(self, service, mock_backend):
        """Successful repair replaces stale warnings with APS-derived caps/validation."""
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

        expected = ["fresh-cap-warning"]
        with (
            patch(
                "services.system_scheduler.validate_trigger_for_platform",
                return_value=[],
            ),
            patch(
                "services.system_scheduler.is_capability_enabled",
                return_value=(True, "enabled", expected),
            ),
        ):
            result = await service.repair_all(
                _mgr_for_repair(name="n", cron="0 9 * * *", scope="user")
            )
        assert result["repaired"] == 1
        reg2 = service._find_registration(service._load_state(), TID)
        assert reg2 is not None
        assert reg2.warnings == expected
        assert "stale warning from prior registration" not in reg2.warnings

        # Second repair: already healthy — no register; warnings stay converged
        mock_backend.register.reset_mock()
        mock_backend.is_registered = AsyncMock(return_value=True)
        with (
            patch(
                "services.system_scheduler.validate_trigger_for_platform",
                return_value=[],
            ),
            patch(
                "services.system_scheduler.is_capability_enabled",
                return_value=(True, "enabled", expected),
            ),
        ):
            result2 = await service.repair_all(
                _mgr_for_repair(name="n", cron="0 9 * * *", scope="user")
            )
        assert result2["repaired"] == 0
        mock_backend.register.assert_not_awaited()
        reg3 = service._find_registration(service._load_state(), TID)
        assert reg3 is not None
        assert reg3.warnings == expected
