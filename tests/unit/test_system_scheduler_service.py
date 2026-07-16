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

TID = "550e8400-e29b-41d4-a716-446655440000"


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


# ---------------------------------------------------------------------------
# Service transactions
# ---------------------------------------------------------------------------


class TestServiceTransactions:
    @pytest.mark.asyncio
    async def test_native_absent_registered_false(self, service, mock_backend):
        service._backend = mock_backend
        mock_backend.is_registered = AsyncMock(return_value=False)
        with _enable_caps(), _valid_trigger():
            await service.register(
                TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        mock_backend.is_registered.return_value = False
        status = await service.get_status(TID)
        assert status.registered is False
        assert status.verified is False

    @pytest.mark.asyncio
    async def test_same_scope_rollback_restores_prior(self, service, mock_backend):
        service._backend = mock_backend
        mock_backend.is_registered = AsyncMock(return_value=False)
        with _enable_caps(), _valid_trigger():
            await service.register(
                TID, "t1", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        # Now native is present for second update
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.export_native_definition = AsyncMock(return_value=b"<Task prior/>")
        # second register fails verify then restore verifies
        mock_backend.verify_registration = AsyncMock(
            side_effect=[(False, "bad"), (True, "restored")]
        )
        mock_backend.register = AsyncMock()
        with _enable_caps(), _valid_trigger():
            with pytest.raises(RuntimeError, match="verification failed"):
                await service.register(
                    TID,
                    "t2",
                    CronTriggerConfig(cron="0 10 * * *"),
                    SystemTaskScope.USER,
                )
        mock_backend.restore_native_definition.assert_called()
        state = service._load_state()
        reg = state.registrations[0]
        assert reg.state in ("active", "error")
        assert reg.observed

    @pytest.mark.asyncio
    async def test_scope_migration_shared_id_no_double_delete(
        self, service, mock_backend
    ):
        service._backend = mock_backend
        mock_backend.same_native_identifier_across_scopes.return_value = True
        mock_backend.is_registered = AsyncMock(return_value=False)
        mock_backend.export_native_definition = AsyncMock(return_value=None)
        with _enable_caps(), _valid_trigger():
            await service.register(
                TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        # migrate: native present, export required
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.export_native_definition = AsyncMock(return_value=b"<Task/>")
        mock_backend.unregister.reset_mock()
        with _enable_caps(), _valid_trigger():
            with patch(
                "services.system_scheduler.is_capability_enabled",
                return_value=(True, "enabled", []),
            ):
                await service.register(
                    TID,
                    "t",
                    CronTriggerConfig(cron="0 9 * * *"),
                    SystemTaskScope.SYSTEM,
                )
        mock_backend.unregister.assert_not_called()
        reg = service._load_state().registrations[0]
        assert reg.desired_scope == SystemTaskScope.SYSTEM
        assert reg.state == "active"
        assert len([o for o in reg.observed if o.present]) == 1

    @pytest.mark.asyncio
    async def test_compensation_failure_preserves_observed(self, service, mock_backend):
        service._backend = mock_backend
        calls = {"n": 0}

        async def is_reg_side(*a, **k):
            calls["n"] += 1
            return calls["n"] > 1

        mock_backend.is_registered = AsyncMock(side_effect=is_reg_side)
        mock_backend.export_native_definition = AsyncMock(return_value=None)
        mock_backend.register = AsyncMock(side_effect=RuntimeError("native boom"))
        mock_backend.unregister = AsyncMock(side_effect=RuntimeError("comp boom"))
        with _enable_caps(), _valid_trigger():
            with pytest.raises(RuntimeError, match="native boom"):
                await service.register(
                    TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
                )
        reg = service._load_state().registrations[0]
        assert reg.state == "error"
        assert reg.pending_operation == "register"
        assert reg.observed
        assert any(o.present for o in reg.observed)

    @pytest.mark.asyncio
    async def test_corrupt_orphan_delete_fails_closed(self, service):
        service._state_file.parent.mkdir(parents=True, exist_ok=True)
        service._state_file.write_text("{bad", encoding="utf-8")
        with pytest.raises(RuntimeError, match="corrupt"):
            await service.begin_orphan_before_delete(TID)

    @pytest.mark.asyncio
    async def test_export_none_refuses_mutation(self, service, mock_backend):
        service._backend = mock_backend
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.export_native_definition = AsyncMock(return_value=None)
        with _enable_caps(), _valid_trigger():
            with pytest.raises(RuntimeError, match="export/snapshot"):
                await service.register(
                    TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
                )
        mock_backend.register.assert_not_called()

    @pytest.mark.asyncio
    async def test_orphan_restore_exact_prior_not_unconditional(
        self, service, mock_backend
    ):
        service._backend = mock_backend
        with _enable_caps(), _valid_trigger():
            # first register: is_registered False so no export required
            mock_backend.is_registered = AsyncMock(return_value=False)
            mock_backend.export_native_definition = AsyncMock(return_value=None)
            await service.register(
                TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        # Force state to error (not active)
        state = service._load_state()
        reg = state.registrations[0]
        reg.state = "error"
        reg.orphaned = False
        reg.last_error = "prior error"
        service._save_state(state)

        assert await service.begin_orphan_before_delete(TID) is True
        await service.restore_active_after_failed_delete(TID)
        reg2 = service._load_state().registrations[0]
        # Must restore exact prior (error), NOT force active
        assert reg2.state == "error"
        assert reg2.orphaned is False
        assert reg2.last_error == "prior error"

    @pytest.mark.asyncio
    async def test_query_exception_not_confirmed_absent(self, service, mock_backend):
        service._backend = mock_backend
        mock_backend.is_registered = AsyncMock(return_value=False)
        mock_backend.export_native_definition = AsyncMock(return_value=None)
        with _enable_caps(), _valid_trigger():
            await service.register(
                TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        mock_backend.is_registered = AsyncMock(
            side_effect=RuntimeError("schtasks boom")
        )
        status = await service.get_status(TID)
        # Should not claim confirmed native absence in observed details
        assert status.observed
        assert any("unknown" in (o.details or "").lower() for o in status.observed)
        assert not any((o.details or "") == "native absent" for o in status.observed)

    @pytest.mark.asyncio
    async def test_repair_export_none_refuses_overwrite(self, service, mock_backend):
        """P0-3: native exists but export returns None → refuse to overwrite."""
        service._backend = mock_backend
        with _enable_caps(), _valid_trigger():
            await service.register(
                TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        # Force path change so repair triggers, AND export returns None
        state = service._load_state()
        state.registrations[0].desired_exe_path = "/different/exe"
        service._save_state(state)
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.export_native_definition = AsyncMock(return_value=None)
        service.set_job_probes(exists=lambda _id: True)
        result = await service.repair_all()
        assert result["failed"] >= 1
        assert any("导出" in d or "export" in d.lower() for d in result["details"])
        reg = service._load_state().registrations[0]
        assert reg.state == "error"
        assert "refusing" in (reg.last_error or "").lower()

    @pytest.mark.asyncio
    async def test_repair_export_exception_refuses_overwrite(
        self, service, mock_backend
    ):
        """P0-3: native exists but export raises → refuse to overwrite."""
        service._backend = mock_backend
        with _enable_caps(), _valid_trigger():
            await service.register(
                TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        state = service._load_state()
        state.registrations[0].desired_exe_path = "/different/exe"
        service._save_state(state)
        mock_backend.is_registered = AsyncMock(return_value=True)
        mock_backend.export_native_definition = AsyncMock(
            side_effect=RuntimeError("schtasks gone")
        )
        service.set_job_probes(exists=lambda _id: True)
        result = await service.repair_all()
        assert result["failed"] >= 1
        assert any("export" in d.lower() for d in result["details"])
        reg = service._load_state().registrations[0]
        assert reg.state == "error"
        assert "refusing" in (reg.last_error or "").lower()

    @pytest.mark.asyncio
    async def test_distinct_id_migrate_verify_fail_cleans_new_target(self, service):
        """P0-4: distinct-ID migration verify failure must unregister new target."""
        b = MagicMock()
        b.platform_name = "linux"
        b.register = AsyncMock()
        b.unregister = AsyncMock()
        b.is_registered = AsyncMock(return_value=True)
        b.export_native_definition = AsyncMock(return_value=b"old cron line")
        b.restore_native_definition = AsyncMock()
        b.same_native_identifier_across_scopes = MagicMock(return_value=False)
        b.build_identifier = MagicMock(
            side_effect=lambda tid, s: f"mwu-{tid}-{s.value}"
        )
        service._backend = b

        # First register with USER – must succeed (verify ok)
        b.verify_registration = AsyncMock(return_value=(True, "ok"))
        with _enable_caps(), _valid_trigger():
            await service.register(
                TID, "t", CronTriggerConfig(cron="0 9 * * *"), SystemTaskScope.USER
            )
        # Now migrate to SYSTEM – verify fails on new target
        b.verify_registration = AsyncMock(
            side_effect=[
                (False, "verify bad"),
                (True, "restored"),
            ]
        )
        b.register.reset_mock()
        b.unregister.reset_mock()
        with (
            _enable_caps(),
            _valid_trigger(),
            patch(
                "services.system_scheduler.is_capability_enabled",
                return_value=(True, "enabled", []),
            ),
        ):
            with pytest.raises(RuntimeError, match="migrate verify"):
                await service.register(
                    TID,
                    "t",
                    CronTriggerConfig(cron="0 9 * * *"),
                    SystemTaskScope.SYSTEM,
                )
        new_unreg_calls = [
            c for c in b.unregister.call_args_list if c[0][1] == SystemTaskScope.SYSTEM
        ]
        assert len(new_unreg_calls) >= 1, (
            "distinct-ID migration must unregister new target on verify failure"
        )
        b.restore_native_definition.assert_called()
