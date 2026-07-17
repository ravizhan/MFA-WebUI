"""Operational state migration and save tests."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import json_utils as json
from models.scheduler import (
    SystemTaskOperationalRecord,
    SystemTaskScope,
    OPERATIONAL_STATE_KEYS,
)
from services.system_scheduler import SystemTaskService, _SystemTaskState, OPERATIONAL_STATE_VERSION


@pytest.fixture
def service(tmp_path: Path) -> SystemTaskService:
    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    return SystemTaskService(tmp_path)


def test_operational_save_only_allowlisted_keys(service: SystemTaskService):
    st = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t1",
            platform="windows",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER, SystemTaskScope.SYSTEM],
            system_task_identifier="\\MWU\\t1",
            registered_exe_path="/bin/mwu",
            last_registered_at=datetime(2026, 7, 1),
            warnings=["w"],
        )
    )
    service._save_state(st)
    data = json.loads(service._state_file.read_text(encoding="utf-8"))
    assert data["version"] == 3
    reg = data["registrations"][0]
    assert set(reg.keys()) <= OPERATIONAL_STATE_KEYS
    for forbidden in (
        "task_name",
        "desired_trigger",
        "desired_scope",
        "desired_exe_path",
        "desired_cli_args",
        "desired_working_dir",
        "trigger_spec",
        "scope",
        "pending_operation",
        "orphaned",
        "migration_from_scope",
    ):
        assert forbidden not in reg
    assert "0 0 * * *" not in service._state_file.read_text(encoding="utf-8")


def test_legacy_load_migrates_in_memory_defers_disk(service: SystemTaskService):
    # Write a legacy (version=2) file with desired mirrors
    legacy = {
        "version": 2,
        "registrations": [
            {
                "task_id": "legacy-1",
                "task_name": "from-json",
                "platform": "windows",
                "desired_scope": "user",
                "desired_trigger": {
                    "trigger_type": "cron",
                    "cron_expression": "0 9 * * *",
                },
                "desired_exe_path": "/old/mwu",
                "desired_cli_args": ["--headless"],
                "state": "pending_register",
                "pending_operation": "register",
                "system_task_identifier": "\\MWU\\legacy-1",
                "registered_exe_path": "/old/mwu",
                "observed": [
                    {
                        "scope": "system",
                        "identifier": "\\MWU\\sys\\legacy-1",
                        "present": True,
                        "verified": False,
                    }
                ],
                "migration_from_scope": "system",
                "orphaned": False,
                "scope": "user",
                "trigger_spec": {
                    "trigger_type": "cron",
                    "cron_expression": "0 9 * * *",
                },
            }
        ],
    }
    service._state_file.parent.mkdir(parents=True, exist_ok=True)
    service._state_file.write_text(json.dumps(legacy), encoding="utf-8")
    service._memory_state = None

    st = service._load_state()
    assert st.pending_operational_flush is True
    assert len(st.records) == 1
    rec = st.records[0]
    assert rec.task_id == "legacy-1"
    assert rec.last_known_scope == SystemTaskScope.USER
    assert SystemTaskScope.USER in rec.cleanup_scopes
    assert SystemTaskScope.SYSTEM in rec.cleanup_scopes  # from observed + pending
    assert rec.state == "error"
    assert rec.last_error and "migrated from legacy" in rec.last_error
    assert rec.registered_exe_path == "/old/mwu"
    # No disk rewrite yet
    on_disk = json.loads(service._state_file.read_text(encoding="utf-8"))
    assert on_disk["version"] == 2
    assert "desired_trigger" in on_disk["registrations"][0]


@pytest.mark.asyncio
async def test_import_allows_first_operational_flush(service: SystemTaskService):
    legacy = {
        "version": 2,
        "registrations": [
            {
                "task_id": "t2",
                "task_name": "n",
                "platform": "linux",
                "desired_scope": "user",
                "desired_trigger": {
                    "trigger_type": "cron",
                    "cron_expression": "0 1 * * *",
                },
                "desired_exe_path": "/x",
                "state": "active",
                "system_task_identifier": "id",
            }
        ],
    }
    service._state_file.write_text(json.dumps(legacy), encoding="utf-8")
    service._memory_state = None
    service._load_state()

    class FakeMgr:
        def import_system_scopes(self, mapping):
            return {
                "imported": 0,
                "skipped": 0,
                "missing_job": 1,
                "failed": 0,
                "details": [],
            }

    await service.import_scopes_into_aps(FakeMgr())  # type: ignore[arg-type]
    data = json.loads(service._state_file.read_text(encoding="utf-8"))
    assert data["version"] == 3
    reg = data["registrations"][0]
    assert set(reg.keys()) <= OPERATIONAL_STATE_KEYS
    assert "desired_trigger" not in reg
    assert "task_name" not in reg


def test_corrupt_fail_closed(service: SystemTaskService):
    service._state_file.write_text("{not-json", encoding="utf-8")
    service._memory_state = None
    st = service._load_state()
    assert st.corrupt is True
    with pytest.raises(RuntimeError, match="corrupt"):
        service._save_state(st)
    # original preserved
    assert service._state_file.read_text(encoding="utf-8") == "{not-json"


def test_atomic_replace_writes_valid_json(service: SystemTaskService, tmp_path: Path):
    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="a",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
        )
    )
    service._save_state(st)
    assert not service._state_file.with_suffix(".json.tmp").exists()
    data = json.loads(service._state_file.read_text(encoding="utf-8"))
    assert data["version"] == 3
    assert data["registrations"][0]["task_id"] == "a"


def test_malformed_legacy_observed_fail_closed(service: SystemTaskService):
    """Malformed observed entries must not migrate into a clean operational record."""
    legacy = {
        "version": 2,
        "registrations": [
            {
                "task_id": "bad-obs",
                "task_name": "n",
                "platform": "linux",
                "desired_scope": "user",
                "desired_trigger": {
                    "trigger_type": "cron",
                    "cron_expression": "0 1 * * *",
                },
                "desired_exe_path": "/x",
                "state": "active",
                "system_task_identifier": "id",
                "observed": [
                    {"scope": "not-a-scope", "identifier": "x"},  # invalid scope
                ],
            }
        ],
    }
    service._state_file.write_text(json.dumps(legacy), encoding="utf-8")
    service._memory_state = None
    st = service._load_state()
    assert st.corrupt is True
    # Must not produce a clean operational record
    assert st.records == []
    with pytest.raises(RuntimeError, match="corrupt"):
        service._save_state(st)
    # Original legacy file preserved
    assert "not-a-scope" in service._state_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_status_aps_none_authoritative_disabled(service: SystemTaskService):
    from unittest.mock import AsyncMock, MagicMock

    from models.scheduler import CronTriggerConfig, ScheduledTask

    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t-none",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
        )
    )
    service._memory_state = st
    service._save_state(st)

    task = ScheduledTask(
        id="t-none",
        name="n",
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        system_scope=None,
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=task)
    status = await service.get_status("t-none", manager=mgr)
    assert status.scope is None
    assert status.desired_scope is None
    assert status.registered is False
    assert status.path_valid is False
    assert status.reason and "None" in status.reason


@pytest.mark.asyncio
async def test_status_aps_missing_not_fabricated(service: SystemTaskService):
    from unittest.mock import AsyncMock, MagicMock

    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t-miss",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
        )
    )
    service._memory_state = st
    service._save_state(st)
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(return_value=False),
        build_identifier=MagicMock(return_value="id"),
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=None)
    status = await service.get_status("t-miss", manager=mgr)
    assert status.registered is False
    assert status.path_valid is False
    assert status.verified is False
    assert status.reason and "APS job missing" in status.reason
    # last_known may appear only as diagnostic via observed, not as active desired
    # when APS is missing we still expose last_known on scope for diagnostics
    # but reason is explicit
    assert "missing" in (status.reason or "").lower()


@pytest.mark.asyncio
async def test_list_registered_authoritative_not_state_only(service: SystemTaskService):
    from unittest.mock import AsyncMock, MagicMock

    from models.scheduler import CronTriggerConfig, ScheduledTask

    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t-list",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
        )
    )
    service._memory_state = st
    service._save_state(st)
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(return_value=False),
        build_identifier=MagicMock(return_value="id"),
        verify_registration=AsyncMock(return_value=(True, "ok")),
    )
    # APS missing despite state=active
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=None)
    regs = await service.list_registered(manager=mgr)
    assert len(regs) == 1
    assert regs[0].registered is False
    assert regs[0].path_valid is False
    assert regs[0].reason and "missing" in regs[0].reason.lower()

    # APS present + native present
    task = ScheduledTask(
        id="t-list",
        name="live",
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        system_scope="user",
    )
    mgr.get_task = AsyncMock(return_value=task)
    service._backend.is_registered = AsyncMock(return_value=True)
    regs2 = await service.list_registered(manager=mgr)
    assert regs2[0].registered is True
    assert regs2[0].task_name == "live"
    assert regs2[0].desired_scope == SystemTaskScope.USER


@pytest.mark.asyncio
async def test_status_list_corrupt_raises(service: SystemTaskService):
    service._state_file.write_text("{bad", encoding="utf-8")
    service._memory_state = None
    with pytest.raises(RuntimeError, match="corrupt"):
        await service.get_status("x")
    with pytest.raises(RuntimeError, match="corrupt"):
        await service.list_registered()


@pytest.mark.asyncio
async def test_path_valid_false_when_registered_exe_empty(service: SystemTaskService):
    """Empty registered_exe_path must never yield path_valid=True."""
    from unittest.mock import AsyncMock, MagicMock

    from models.scheduler import CronTriggerConfig, ScheduledTask

    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t-empty-path",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
            registered_exe_path="",  # empty diagnostic
        )
    )
    service._memory_state = st
    service._save_state(st)
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(return_value=True),
        verify_registration=AsyncMock(return_value=(True, "ok")),
        build_identifier=MagicMock(return_value="id"),
    )
    task = ScheduledTask(
        id="t-empty-path",
        name="n",
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        system_scope="user",
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=task)
    status = await service.get_status("t-empty-path", manager=mgr)
    assert status.registered is True
    assert status.verified is True
    assert status.path_valid is False


@pytest.mark.asyncio
async def test_path_valid_true_only_when_nonempty_matches(service: SystemTaskService):
    from unittest.mock import AsyncMock, MagicMock

    from models.scheduler import CronTriggerConfig, ScheduledTask

    exe = service.current_exe_path
    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t-match",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
            registered_exe_path=exe,
        )
    )
    service._memory_state = st
    service._save_state(st)
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(return_value=True),
        verify_registration=AsyncMock(return_value=(True, "ok")),
        build_identifier=MagicMock(return_value="id"),
    )
    task = ScheduledTask(
        id="t-match",
        name="n",
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        system_scope="user",
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=task)
    status = await service.get_status("t-match", manager=mgr)
    assert status.path_valid is True

    # native absent => path_valid false even with matching diagnostic path
    service._backend.is_registered = AsyncMock(return_value=False)
    status2 = await service.get_status("t-match", manager=mgr)
    assert status2.registered is False
    assert status2.path_valid is False


@pytest.mark.asyncio
async def test_aps_missing_diagnostic_present_true(service: SystemTaskService):
    """APS missing: registered=false, but observed.present=True if historical native present."""
    from unittest.mock import AsyncMock, MagicMock

    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t-hist",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
            system_task_identifier="hist-id",
        )
    )
    service._memory_state = st
    service._save_state(st)
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(return_value=True),  # historical still present
        build_identifier=MagicMock(return_value="hist-id"),
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=None)
    status = await service.get_status("t-hist", manager=mgr)
    assert status.registered is False
    assert status.verified is False
    assert status.path_valid is False
    assert status.reason and "APS job missing" in status.reason
    assert status.observed
    hist = next(o for o in status.observed if o.scope == SystemTaskScope.USER)
    assert hist.present is True
    assert hist.verified is False


@pytest.mark.asyncio
async def test_aps_missing_diagnostic_unknown_observed_false(service: SystemTaskService):
    from unittest.mock import AsyncMock, MagicMock

    st = _SystemTaskState(version=3)
    st.pending_operational_flush = False
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t-unk",
            platform="linux",
            state="active",
            last_known_scope=SystemTaskScope.USER,
            cleanup_scopes=[SystemTaskScope.USER],
        )
    )
    service._memory_state = st
    service._save_state(st)
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(side_effect=RuntimeError("schtasks boom")),
        build_identifier=MagicMock(return_value="id"),
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=None)
    status = await service.get_status("t-unk", manager=mgr)
    assert status.registered is False
    assert status.observed
    hist = next(o for o in status.observed if o.scope == SystemTaskScope.USER)
    assert hist.present is False
    assert "unknown" in (hist.details or "").lower()
