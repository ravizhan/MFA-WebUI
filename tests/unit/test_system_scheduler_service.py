"""SystemTaskService unit tests — transactional state, recovery, orphans."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    CronTriggerConfig,
    OSTriggerSpec,
    SystemTaskRegistration,
    SystemTaskScope,
)
from services.system_scheduler import SystemTaskService, _SystemTaskState


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    return tmp_path


@pytest.fixture
def service(temp_config_dir: Path) -> SystemTaskService:
    return SystemTaskService(temp_config_dir)


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.platform_name = "windows"
    backend.register = AsyncMock()
    backend.unregister = AsyncMock()
    backend.is_registered = AsyncMock(return_value=False)
    backend.get_next_run_time = AsyncMock(return_value=None)
    backend.list_registered = AsyncMock(return_value=[])
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    backend.build_identifier = MagicMock(side_effect=lambda tid, scope: f"\\MWU\\{tid}")
    backend.export_native_definition = AsyncMock(return_value=None)
    backend.restore_native_definition = AsyncMock()
    backend.same_native_identifier_across_scopes = MagicMock(return_value=True)
    return backend


def _enable_caps():
    return patch(
        "services.system_scheduler.is_capability_enabled",
        return_value=(True, "enabled", []),
    )


def _valid_trigger():
    return patch(
        "services.system_scheduler.validate_trigger_for_platform",
        return_value=[],
    )


# ---------------------------------------------------------------------------
# 状态持久化
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_load_empty_state(self, service: SystemTaskService):
        state = service._load_state()
        assert state.version == 2
        assert len(state.registrations) == 0

    def test_save_and_load(self, service: SystemTaskService):
        state = _SystemTaskState()
        state.registrations.append(
            SystemTaskRegistration(
                task_id="550e8400-e29b-41d4-a716-446655440000",
                task_name="测试任务",
                platform="windows",
                desired_scope=SystemTaskScope.USER,
                desired_trigger=OSTriggerSpec(
                    trigger_type="cron", cron_expression="0 9 * * *"
                ),
                desired_exe_path="/usr/bin/mwu",
                system_task_identifier="\\MWU\\550e8400-e29b-41d4-a716-446655440000",
                registered_exe_path="/usr/bin/mwu",
                last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
                state="active",
                orphaned=False,
            )
        )
        service._save_state(state)

        loaded = service._load_state()
        assert len(loaded.registrations) == 1
        reg = loaded.registrations[0]
        assert reg.task_id == "550e8400-e29b-41d4-a716-446655440000"
        assert reg.state == "active"
        assert reg.desired_trigger.cron_expression == "0 9 * * *"

    def test_load_corrupted_file_fail_closed(self, service: SystemTaskService):
        service._state_file.parent.mkdir(parents=True, exist_ok=True)
        service._state_file.write_text("{ invalid json", encoding="utf-8")
        state = service._load_state()
        assert state.corrupt is True
        assert len(state.registrations) == 0
        # original corrupt preserved
        assert service._state_file.exists()
        with pytest.raises(RuntimeError, match="corrupt"):
            service._save_state(state)


# ---------------------------------------------------------------------------
# 注册/卸载流程
# ---------------------------------------------------------------------------


class TestRegisterUnregister:
    @pytest.mark.asyncio
    async def test_register_pending_before_native(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"

        seen_states = []

        async def tracking_register(spec):
            # During native call, durable state must already be pending_register
            st = service._load_state()
            reg = service._find_registration(st, tid)
            assert reg is not None
            assert reg.state == "pending_register"
            assert reg.pending_operation == "register"
            seen_states.append(reg.state)

        mock_backend.register = AsyncMock(side_effect=tracking_register)

        # After register, is_registered should report present for status
        async def is_reg_after_create(*a, **k):
            return mock_backend.register.await_count > 0

        mock_backend.is_registered = AsyncMock(side_effect=is_reg_after_create)

        with _enable_caps(), _valid_trigger():
            status = await service.register(
                task_id=tid,
                task_name="测试任务",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )

        assert status.registered is True
        assert status.state == "active"
        assert seen_states == ["pending_register"]
        mock_backend.verify_registration.assert_called()

    @pytest.mark.asyncio
    async def test_register_failure_compensates(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"
        mock_backend.register = AsyncMock(side_effect=RuntimeError("native fail"))

        with _enable_caps(), _valid_trigger():
            with pytest.raises(RuntimeError, match="native fail"):
                await service.register(
                    task_id=tid,
                    task_name="测试",
                    trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                    scope=SystemTaskScope.USER,
                )

        mock_backend.unregister.assert_called()
        state = service._load_state()
        reg = service._find_registration(state, tid)
        assert reg is not None
        assert reg.state == "error"

    @pytest.mark.asyncio
    async def test_unregister_pending_cleanup(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"

        with _enable_caps(), _valid_trigger():
            await service.register(
                task_id=tid,
                task_name="测试",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )

        mock_backend.is_registered = AsyncMock(return_value=False)
        status = await service.unregister(tid)
        assert status.registered is False
        assert len(service._load_state().registrations) == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        status = await service.unregister("550e8400-e29b-41d4-a716-446655440000")
        assert status.registered is False
        mock_backend.unregister.assert_not_called()

    @pytest.mark.asyncio
    async def test_capability_rejection(self, service: SystemTaskService, mock_backend):
        service._backend = mock_backend
        with (
            patch(
                "services.system_scheduler.is_capability_enabled",
                return_value=(False, "disabled for test", []),
            ),
            _valid_trigger(),
        ):
            with pytest.raises(ValueError, match="capability disabled"):
                await service.register(
                    task_id="550e8400-e29b-41d4-a716-446655440000",
                    task_name="x",
                    trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                    scope=SystemTaskScope.USER,
                )


# ---------------------------------------------------------------------------
# 自愈 / 孤儿
# ---------------------------------------------------------------------------


class TestRepairAndOrphan:
    @pytest.mark.asyncio
    async def test_mark_orphaned_never_autorepair(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"
        with _enable_caps(), _valid_trigger():
            await service.register(
                task_id=tid,
                task_name="测试",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )
        await service.mark_orphaned(tid)
        state = service._load_state()
        assert state.registrations[0].state == "orphaned"
        assert state.registrations[0].orphaned is True

        mock_backend.is_registered.return_value = False
        result = await service.repair_all()
        # orphan skipped — not reactivated
        state = service._load_state()
        assert state.registrations[0].state == "orphaned"
        assert any("orphan" in d for d in result["details"])

    @pytest.mark.asyncio
    async def test_missing_job_becomes_orphaned(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"
        with _enable_caps(), _valid_trigger():
            await service.register(
                task_id=tid,
                task_name="测试",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )
        service.set_job_probes(exists=lambda _id: False)
        await service.repair_all()
        assert service._load_state().registrations[0].state == "orphaned"

    @pytest.mark.asyncio
    async def test_disabled_job_remains_active(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"
        with _enable_caps(), _valid_trigger():
            await service.register(
                task_id=tid,
                task_name="测试",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )
        service.set_job_probes(exists=lambda _id: True, enabled=lambda _id: False)
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.export_native_definition = AsyncMock(return_value=b"<Task/>")
        result = await service.repair_all()
        assert service._load_state().registrations[0].state == "active"
        assert any("active-but-disabled" in d for d in result["details"])

    @pytest.mark.asyncio
    async def test_recovery_promotes_pending(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"
        # Manually write pending_register intent as if crash mid-register
        state = _SystemTaskState()
        state.registrations.append(
            SystemTaskRegistration(
                task_id=tid,
                task_name="crash",
                platform="windows",
                desired_scope=SystemTaskScope.USER,
                desired_trigger=OSTriggerSpec(
                    trigger_type="cron", cron_expression="0 9 * * *"
                ),
                desired_exe_path="python",
                desired_cli_args=["main.py", "--headless", "--task", tid],
                desired_working_dir=str(service._app_root_dir),
                state="pending_register",
                pending_operation="register",
                system_task_identifier=f"\\MWU\\{tid}",
                registered_exe_path="python",
            )
        )
        service._save_state(state)
        mock_backend.is_registered.return_value = True
        mock_backend.verify_registration.return_value = (True, "ok")
        result = await service.recover_pending()
        assert result["recovered"] >= 1
        assert service._load_state().registrations[0].state == "active"


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_get_status_registered(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        tid = "550e8400-e29b-41d4-a716-446655440000"
        with _enable_caps(), _valid_trigger():
            await service.register(
                task_id=tid,
                task_name="测试",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.verify_registration = AsyncMock(return_value=(True, "ok"))
        status = await service.get_status(tid)
        assert status.registered is True
        assert status.state == "active"
        assert status.desired_scope == SystemTaskScope.USER

    @pytest.mark.asyncio
    async def test_get_status_not_registered(
        self, service: SystemTaskService, mock_backend
    ):
        service._backend = mock_backend
        status = await service.get_status("550e8400-e29b-41d4-a716-446655440000")
        assert status.registered is False
