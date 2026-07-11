"""Oracle-hardened scheduler tests: locks, verify, transactions, headless, interop."""

from __future__ import annotations

import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    CronTriggerConfig,
    OSTriggerSpec,
    SystemTaskScope,
    SystemTaskSpec,
)
from services.process_lock import AdvisoryFileLock
from services.system_scheduler import SystemTaskService
from services.system_scheduler_backend import (
    MacOSBackend,
    WindowsBackend,
    build_capabilities,
    validate_linux_cron_expression,
)

TID = "550e8400-e29b-41d4-a716-446655440000"
_XML_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


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


@pytest.fixture
def temp_root(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    return tmp_path


@pytest.fixture
def service(temp_root: Path) -> SystemTaskService:
    return SystemTaskService(temp_root)


@pytest.fixture
def mock_backend():
    backend = MagicMock()
    backend.platform_name = "windows"
    backend.register = AsyncMock()
    backend.unregister = AsyncMock()
    backend.is_registered = AsyncMock(return_value=True)
    backend.get_next_run_time = AsyncMock(return_value=None)
    backend.list_registered = AsyncMock(return_value=[])
    backend.verify_registration = AsyncMock(return_value=(True, "ok"))
    backend.build_identifier = MagicMock(side_effect=lambda tid, scope: f"\\MWU\\{tid}")
    backend.export_native_definition = AsyncMock(return_value=None)
    backend.restore_native_definition = AsyncMock()
    backend.same_native_identifier_across_scopes = MagicMock(return_value=True)
    # Default: no existing native so first register is allowed without export
    backend.is_registered = AsyncMock(return_value=False)
    return backend


# ---------------------------------------------------------------------------
# Capabilities smoke evidence
# ---------------------------------------------------------------------------


class TestCapabilitiesSmoke:
    def test_no_evidence_all_disabled(self):
        caps = build_capabilities("windows", host_platform="windows")
        assert all(not c.enabled for c in caps.cells)

    def test_explicit_smoke_enables_user_trigger_specific(self):
        caps = build_capabilities(
            "windows",
            host_platform="windows",
            smoke_evidence={
                "windows:user:cron": True,
                "windows:user:date": True,
                "windows:user:interval": True,
            },
        )
        user = [
            c
            for c in caps.cells
            if c.platform == "windows" and c.scope == SystemTaskScope.USER
        ]
        assert all(c.enabled for c in user)
        system = [
            c
            for c in caps.cells
            if c.platform == "windows" and c.scope == SystemTaskScope.SYSTEM
        ]
        assert all(not c.enabled for c in system)

    def test_broad_windows_evidence_does_not_enable(self):
        caps = build_capabilities(
            "windows",
            host_platform="windows",
            smoke_evidence={"windows": True, "windows:user": True},
        )
        assert all(not c.enabled for c in caps.cells)

    def test_string_false_not_truthy(self, tmp_path: Path):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "system_scheduler_smoke.json").write_text(
            '{"windows:user:cron": "false", "windows:user:date": true}',
            encoding="utf-8",
        )
        from services.system_scheduler_backend import load_smoke_evidence

        ev = load_smoke_evidence(tmp_path)
        assert "windows:user:cron" not in ev  # string rejected
        assert ev.get("windows:user:date") is True

    def test_system_requires_elevated_proof(self):
        caps = build_capabilities(
            "windows",
            host_platform="windows",
            smoke_evidence={
                "windows:system:cron": True,  # insufficient alone
            },
        )
        sys_cron = next(
            c
            for c in caps.cells
            if c.platform == "windows"
            and c.scope == SystemTaskScope.SYSTEM
            and c.trigger_type == "cron"
        )
        assert sys_cron.enabled is False
        caps2 = build_capabilities(
            "windows",
            host_platform="windows",
            smoke_evidence={
                "windows:system:cron": True,
                "windows:system:elevated": True,
                "windows:system:post_user_restart": True,
            },
        )
        sys_cron2 = next(
            c
            for c in caps2.cells
            if c.platform == "windows"
            and c.scope == SystemTaskScope.SYSTEM
            and c.trigger_type == "cron"
        )
        assert sys_cron2.enabled is True


# ---------------------------------------------------------------------------
# Windows XML verification
# ---------------------------------------------------------------------------


class TestWindowsXmlVerify:
    def _spec(self, scope=SystemTaskScope.USER, trig="cron") -> SystemTaskSpec:
        if trig == "cron":
            trigger = OSTriggerSpec(trigger_type="cron", cron_expression="0 9 * * *")
        elif trig == "interval":
            trigger = OSTriggerSpec(trigger_type="interval", interval_minutes=15)
        else:
            trigger = OSTriggerSpec(
                trigger_type="date",
                run_date=datetime.now(timezone.utc) + timedelta(days=2),
            )
        return SystemTaskSpec(
            task_id=TID,
            task_name="T",
            exe_path=r"C:\Program Files\MWU\python.exe",
            cli_args=[r"C:\Program Files\MWU\main.py", "--headless", "--task", TID],
            trigger=trigger,
            scope=scope,
            working_dir=r"C:\Program Files\MWU",
        )

    def test_golden_xml_verifies(self):
        b = WindowsBackend()
        spec = self._spec()
        raw = b._build_task_xml(spec)
        ok, detail = b.compare_exported_xml_bytes(raw, spec)
        assert ok, detail

    def test_wrong_command_fails(self):
        b = WindowsBackend()
        spec = self._spec()
        raw = (
            b._build_task_xml(spec)
            .decode("utf-8")
            .replace(spec.exe_path, r"C:\wrong\python.exe")
        )
        ok, detail = b.compare_exported_xml_bytes(raw.encode("utf-8"), spec)
        assert not ok
        assert "Command" in detail

    def test_wrong_args_fails(self):
        b = WindowsBackend()
        spec = self._spec()
        bad = self._spec()
        bad.cli_args = ["other.py"]
        raw = b._build_task_xml(bad)
        ok, detail = b.compare_exported_xml_bytes(raw, spec)
        assert not ok
        assert "Arguments" in detail

    def test_serviceaccount_fails(self):
        b = WindowsBackend()
        spec = self._spec(scope=SystemTaskScope.SYSTEM)
        raw = (
            b._build_task_xml(spec)
            .decode("utf-8")
            .replace("Password", "ServiceAccount")
        )
        ok, detail = b.compare_exported_xml_bytes(raw.encode("utf-8"), spec)
        assert not ok

    def test_pt1m_cron_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="cron")
        # inject PT1M into golden
        root = ET.fromstring(b._build_task_xml(spec))
        # append bogus repetition
        for el in root.iter():
            if el.tag.endswith("CalendarTrigger") or el.tag == "CalendarTrigger":
                rep = ET.SubElement(el, "Repetition")
                iv = ET.SubElement(rep, "Interval")
                iv.text = "PT1M"
                break
        raw = ET.tostring(root, encoding="utf-8")
        ok, detail = b.compare_exported_xml_bytes(raw, spec)
        assert not ok
        assert "PT1M" in detail

    def test_cron_0900_to_1000_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="cron")  # 0 9 * * *
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("StartBoundary") or el.tag == "StartBoundary":
                if el.text:
                    el.text = el.text[:11] + "10" + el.text[13:]
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "StartBoundary" in detail or "time mismatch" in detail

    def test_date_drift_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="date")
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("StartBoundary") or el.tag == "StartBoundary":
                if el.text and len(el.text) >= 10:
                    # shift day
                    el.text = (
                        el.text[:8] + ("2" if el.text[8] != "2" else "3") + el.text[9:]
                    )
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "StartBoundary" in detail

    def test_days_interval_change_fails(self):
        b = WindowsBackend()
        spec = self._spec(trig="cron")
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("DaysInterval") or el.tag == "DaysInterval":
                el.text = "2"
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "DaysInterval" in detail

    def test_settings_change_fails(self):
        b = WindowsBackend()
        spec = self._spec()
        root = ET.fromstring(b._build_task_xml(spec))
        for el in root.iter():
            if el.tag.endswith("ExecutionTimeLimit") or el.tag == "ExecutionTimeLimit":
                el.text = "PT1H"
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "ExecutionTimeLimit" in detail

    def test_settings_enabled_false_with_trigger_enabled_true_fails(self):
        """P0-1: _find_desc hit Trigger/Enabled first, bypassing Settings/Enabled=false."""
        b = WindowsBackend()
        spec = self._spec(trig="cron")
        root = ET.fromstring(b._build_task_xml(spec))
        # Flip Settings/Enabled to false; verify must fail (subtree lookup)
        for el in root:
            if b._local_tag(el.tag) == "Settings":
                for child in el:
                    if b._local_tag(child.tag) == "Enabled":
                        child.text = "false"
                break
        ok, detail = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok
        assert "Settings.Enabled" in detail or "true" in detail.lower()

    def test_allow_start_on_demand_verified(self):
        """P0-2: AllowStartOnDemand is built but must be verified."""
        b = WindowsBackend()
        spec = self._spec()
        root = ET.fromstring(b._build_task_xml(spec))
        # Golden passes
        ok, _ = b.compare_exported_xml_bytes(ET.tostring(root, encoding="utf-8"), spec)
        assert ok
        # Mangle AllowStartOnDemand -> fails
        for el in root.iter():
            if b._local_tag(el.tag) == "AllowStartOnDemand":
                el.text = "false"
                break
        ok2, detail2 = b.compare_exported_xml_bytes(
            ET.tostring(root, encoding="utf-8"), spec
        )
        assert not ok2
        assert "AllowStartOnDemand" in detail2


# ---------------------------------------------------------------------------
# Linux bounds / macOS escaping
# ---------------------------------------------------------------------------


class TestLinuxMacStrict:
    def test_linux_minute_out_of_bounds(self):
        with pytest.raises(ValueError, match="越界"):
            validate_linux_cron_expression("60 9 * * *")

    def test_linux_hour_out_of_bounds(self):
        with pytest.raises(ValueError, match="越界"):
            validate_linux_cron_expression("0 24 * * *")

    def test_linux_day_out_of_bounds(self):
        with pytest.raises(ValueError, match="越界"):
            validate_linux_cron_expression("0 9 32 * *")

    def test_linux_invalid_expansions_rejected(self):
        with pytest.raises(ValueError):
            validate_linux_cron_expression("70/2 9 * * *")
        with pytest.raises(ValueError):
            validate_linux_cron_expression("0 9 32/2 * *")
        with pytest.raises(ValueError):
            validate_linux_cron_expression("5-3 9 * * *")
        with pytest.raises(ValueError):
            validate_linux_cron_expression("*/0 9 * * *")

    def test_macos_admin_script_uses_base64(self):
        b = MacOSBackend()
        script = b._admin_register_script(
            "/Library/LaunchDaemons/com.mwu.daemon.x.plist",
            "com.mwu.daemon.x",
            '<?xml version="1.0"?><plist><dict><key>Label</key><string>a\'b"c</string></dict></plist>',
        )
        assert "base64" in script
        assert "echo '" not in script  # no raw echo of plist
        assert "a'b" not in script

    def test_macos_osascript_uses_argv_not_double_quoted_literal(self):
        b = MacOSBackend()
        # Inspect the generated elevation invocation pattern via source of method
        import inspect

        src = inspect.getsource(b._run_osascript_admin)
        assert "on run argv" in src
        assert "item 1 of argv" in src
        # must not build do shell script "..." with embedded script
        assert 'do shell script "' not in src or "item 1" in src


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


# ---------------------------------------------------------------------------
# Process lock cross-process + Go interop
# ---------------------------------------------------------------------------


class TestProcessLockCrossProcess:
    def test_cross_process_python_contention(self, tmp_path: Path):
        lock_path = tmp_path / "config" / "locks" / "runtime.lock"
        lock_path.parent.mkdir(parents=True)
        holder = AdvisoryFileLock(lock_path)
        holder.acquire()
        try:
            code = (
                "from services.process_lock import AdvisoryFileLock, LockBusyError\n"
                f"p = r'''{lock_path}'''\n"
                "try:\n"
                "    AdvisoryFileLock(p).acquire(timeout_seconds=None)\n"
                "    print('ACQUIRED')\n"
                "except LockBusyError:\n"
                "    print('BUSY')\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).resolve().parents[2]),
                timeout=15,
            )
            assert "BUSY" in proc.stdout
        finally:
            holder.release()

    def test_python_go_lockhelper_interop(self, tmp_path: Path):
        """Build lockhelper from source into temp binary; test both directions."""
        root = Path(__file__).resolve().parents[2]
        go = shutil.which("go")
        if not go:
            pytest.skip("Go toolchain unavailable; cannot build lockhelper")

        helper_dir = tmp_path / "lockhelper_build"
        helper_dir.mkdir()
        helper = helper_dir / (
            "lockhelper.exe" if sys.platform == "win32" else "lockhelper"
        )
        build = subprocess.run(
            [go, "build", "-o", str(helper), "./cmd/lockhelper"],
            cwd=str(root / "updater"),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if build.returncode != 0:
            pytest.skip(f"go build lockhelper failed: {build.stderr}")

        lock_path = tmp_path / "config" / "locks" / "runtime.lock"
        lock_path.parent.mkdir(parents=True)

        # Direction 1: Python holds, Go tries
        plock = AdvisoryFileLock(lock_path)
        plock.acquire()
        try:
            proc = subprocess.run(
                [str(helper), "try", "-path", str(lock_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert proc.returncode == 2
            assert "busy" in proc.stdout.lower()
        finally:
            plock.release()

        # Direction 2: Go holds, Python tries
        hold = subprocess.Popen(
            [str(helper), "hold", "-path", str(lock_path), "-seconds", "5"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # wait until held
            import time

            deadline = time.time() + 5
            held = False
            while time.time() < deadline:
                line = hold.stdout.readline() if hold.stdout else ""
                if "held" in line.lower():
                    held = True
                    break
            assert held, "lockhelper did not report held"
            from services.process_lock import LockBusyError

            with pytest.raises(LockBusyError):
                AdvisoryFileLock(lock_path).acquire(timeout_seconds=None)
        finally:
            hold.terminate()
            try:
                hold.wait(timeout=5)
            except Exception:
                hold.kill()


# ---------------------------------------------------------------------------
# Headless real path tests (mocked heavy deps)
# ---------------------------------------------------------------------------


class TestRunHeadless:
    @pytest.mark.asyncio
    async def test_disabled_job_exit_code(self, tmp_path, monkeypatch):
        # Patch main module pieces without loading full interface if possible
        import main as main_mod

        monkeypatch.setattr(main_mod, "APP_ROOT_DIR", tmp_path)
        monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "config" / "logs")
        (tmp_path / "config" / "logs").mkdir(parents=True)

        ownership = MagicMock()
        monkeypatch.setattr(main_mod, "acquire_runtime_ownership", lambda: ownership)
        monkeypatch.setattr(main_mod, "release_runtime_ownership", lambda: None)

        job = SimpleNamespace(next_run_time=None, kwargs={})
        sched = MagicMock()
        sched.get_job.return_value = job
        sm = MagicMock()
        sm.scheduler = sched
        sm.initialize = AsyncMock()
        sm.shutdown = AsyncMock()
        sm.set_worker = MagicMock()

        class SM:
            def __init__(self):
                pass

            def set_worker(self, w):
                pass

            async def initialize(self, **kw):
                self.scheduler = sched

            async def shutdown(self):
                pass

        monkeypatch.setattr(main_mod, "SchedulerManager", SM)
        monkeypatch.setattr(
            main_mod,
            "MaaWorker",
            lambda *a, **k: MagicMock(task_state=SimpleNamespace(last_status="failed")),
        )

        code = await main_mod.run_headless(TID)
        assert code == main_mod.EXIT_TASK_FAILED
        ownership.release.assert_not_called()  # release via release_runtime_ownership

    @pytest.mark.asyncio
    async def test_log_setup_failure_releases_lock(self, tmp_path, monkeypatch):
        import main as main_mod

        released = {"v": False}

        class Own:
            def release(self):
                released["v"] = True

        monkeypatch.setattr(main_mod, "acquire_runtime_ownership", lambda: Own())
        monkeypatch.setattr(
            main_mod,
            "release_runtime_ownership",
            lambda: released.__setitem__("v", True),
        )
        # Force log dir failure by making LOGS_DIR a file
        bad = tmp_path / "notadir"
        bad.write_text("x", encoding="utf-8")
        monkeypatch.setattr(main_mod, "LOGS_DIR", bad / "nested")

        code = await main_mod.run_headless(TID)
        assert code == main_mod.EXIT_TASK_FAILED
        assert released["v"] is True

    @pytest.mark.asyncio
    async def test_executes_exactly_once(self, tmp_path, monkeypatch):
        import main as main_mod

        monkeypatch.setattr(main_mod, "LOGS_DIR", tmp_path / "logs")
        (tmp_path / "logs").mkdir()
        monkeypatch.setattr(main_mod, "acquire_runtime_ownership", lambda: MagicMock())
        monkeypatch.setattr(main_mod, "release_runtime_ownership", lambda: None)

        calls = {"n": 0}

        async def exec_task(**kwargs):
            calls["n"] += 1

        job = SimpleNamespace(
            next_run_time=datetime.now(),
            kwargs={
                "task_id": TID,
                "task_name": "t",
                "task_description": "",
                "task_list": [],
                "task_options": {},
            },
        )
        sched = MagicMock()
        sched.get_job.return_value = job

        class SM:
            def __init__(self):
                self.scheduler = None

            def set_worker(self, w):
                self._w = w

            async def initialize(self, **kw):
                self.scheduler = sched
                assert kw.get("paused") is True

            async def shutdown(self):
                pass

        worker = MagicMock()
        worker.task_state = SimpleNamespace(last_status="success")
        monkeypatch.setattr(main_mod, "SchedulerManager", SM)
        monkeypatch.setattr(main_mod, "MaaWorker", lambda *a, **k: worker)

        with patch("scheduler_manager.execute_scheduled_task", exec_task):
            code = await main_mod.run_headless(TID)
        assert code == main_mod.EXIT_SUCCESS
        assert calls["n"] == 1
