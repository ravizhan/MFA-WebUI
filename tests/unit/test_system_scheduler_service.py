"""SystemTaskService unit tests — core native register/repair only."""

from datetime import datetime
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    CronTriggerConfig,
    OSTriggerSpec,
    SystemTaskRegistration,
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
    st = _SystemTaskState()
    st.registrations.append(
        SystemTaskRegistration(
            task_id=TID,
            task_name="task",
            platform="windows",
            desired_scope=SystemTaskScope.USER,
            desired_trigger=OSTriggerSpec(
                trigger_type="cron", cron_expression="0 9 * * *"
            ),
            desired_exe_path=exe,
            system_task_identifier=f"\\MWU\\{TID}",
            registered_exe_path=exe,
            last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
            state=state,
            orphaned=orphaned,
        )
    )
    svc._save_state(st)


class TestStatePersistence:
    def test_load_empty_state(self, service: SystemTaskService):
        state = service._load_state()
        assert state.version == 2
        assert state.registrations == []

    def test_save_and_load(self, service: SystemTaskService):
        _seed(service)
        loaded = service._load_state()
        assert len(loaded.registrations) == 1
        assert loaded.registrations[0].task_id == TID
        assert loaded.registrations[0].state == "active"

    def test_load_corrupted_file_fail_closed(self, service: SystemTaskService):
        service._state_file.parent.mkdir(parents=True, exist_ok=True)
        service._state_file.write_text("{ invalid json", encoding="utf-8")
        state = service._load_state()
        assert state.corrupt is True
        with pytest.raises(RuntimeError, match="corrupt"):
            service._save_state(state)


class TestRegisterUnregister:
    @pytest.mark.asyncio
    async def test_pending_then_active_after_verify(self, service, mock_backend):
        service._backend = mock_backend
        seen: list[str] = []

        async def tracking_register(_spec):
            reg = service._find_registration(service._load_state(), TID)
            assert reg is not None and reg.state == "pending_register"
            seen.append(reg.state)

        mock_backend.register = AsyncMock(side_effect=tracking_register)
        with _caps(), _trig():
            status = await service.register(
                TID, "task", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        assert status.state == "active" and status.registered is True
        assert seen == ["pending_register"]
        mock_backend.verify_registration.assert_awaited()

    @pytest.mark.asyncio
    async def test_register_failure_cleanup_error(self, service, mock_backend):
        service._backend = mock_backend
        mock_backend.register = AsyncMock(side_effect=RuntimeError("native fail"))
        # Still present after compensation unregister → recorded in last_error
        mock_backend.is_registered = AsyncMock(return_value=True)
        with _caps(), _trig():
            with pytest.raises(RuntimeError, match="native fail"):
                await service.register(
                    TID,
                    "task",
                    CronTriggerConfig(cron="0 9 * * *"),
                    SystemTaskScope.USER,
                )
        mock_backend.unregister.assert_awaited()
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "error"
        assert "still present" in (reg.last_error or "")
        assert reg.observed and any(o.present for o in reg.observed)

    @pytest.mark.asyncio
    async def test_unregister_cleanup(self, service, mock_backend):
        service._backend = mock_backend
        with _caps(), _trig():
            await service.register(
                TID, "task", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        mock_backend.is_registered = AsyncMock(return_value=False)
        status = await service.unregister(TID)
        assert status.registered is False
        assert service._load_state().registrations == []

    @pytest.mark.asyncio
    async def test_capability_rejection(self, service, mock_backend):
        service._backend = mock_backend
        with _caps(ok=False, reason="disabled for test"), _trig():
            with pytest.raises(ValueError, match="capability disabled"):
                await service.register(
                    TID,
                    "x",
                    CronTriggerConfig(cron="0 9 * * *"),
                    SystemTaskScope.USER,
                )
        mock_backend.register.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scope_change_unregisters_old(self, service, mock_backend):
        service._backend = mock_backend
        with _caps(), _trig():
            await service.register(
                TID, "task", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        mock_backend.is_registered = AsyncMock(return_value=False)
        mock_backend.unregister.reset_mock()
        with _caps(), _trig():
            await service.register(
                TID,
                "task",
                CronTriggerConfig(cron="0 9 * * *"),
                SystemTaskScope.SYSTEM,
            )
        mock_backend.unregister.assert_awaited()
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None
        assert reg.desired_scope == SystemTaskScope.SYSTEM
        assert reg.state == "active"


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_unknown_query(self, service, mock_backend):
        service._backend = mock_backend
        with _caps(), _trig():
            await service.register(
                TID, "task", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        mock_backend.is_registered = AsyncMock(side_effect=RuntimeError("schtasks boom"))
        status = await service.get_status(TID)
        assert status.observed
        assert any("unknown" in (o.details or "").lower() for o in status.observed)

    @pytest.mark.asyncio
    async def test_get_status_not_registered(self, service, mock_backend):
        service._backend = mock_backend
        status = await service.get_status(TID)
        assert status.registered is False


class TestRepair:
    @pytest.mark.asyncio
    async def test_repair_success_missing_native(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        result = await service.repair_all()
        assert result["repaired"] == 1
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "active"
        mock_backend.register.assert_awaited()

    @pytest.mark.asyncio
    async def test_repair_failure_persists_error(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service)
        mock_backend.is_registered = AsyncMock(return_value=False)
        mock_backend.register = AsyncMock(side_effect=RuntimeError("repair boom"))
        result = await service.repair_all()
        assert result["failed"] == 1
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "error"
        assert reg.pending_operation == "repair"
        mock_backend.unregister.assert_awaited()

    @pytest.mark.asyncio
    async def test_legacy_orphan_skipped(self, service, mock_backend):
        service._backend = mock_backend
        _seed(service, state="orphaned", orphaned=True)
        result = await service.repair_all()
        assert any("orphan" in d for d in result["details"])
        mock_backend.register.assert_not_awaited()
        reg = service._find_registration(service._load_state(), TID)
        assert reg is not None and reg.state == "orphaned"
