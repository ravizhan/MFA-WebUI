"""Operational state v4 schema: load/save allowlist, fail-closed, status."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import json_utils as json
from models.scheduler import (
    OPERATIONAL_STATE_KEYS,
    OPERATIONAL_STATE_VERSION,
    CronTriggerConfig,
    ScheduledTask,
    SystemTaskOperationalRecord,
)
from services.system_scheduler import SystemTaskService, _SystemTaskState

TID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture
def service(tmp_path: Path) -> SystemTaskService:
    (tmp_path / "config").mkdir()
    (tmp_path / "main.py").write_text("# main", encoding="utf-8")
    return SystemTaskService(tmp_path)


def _seed_v4(
    service: SystemTaskService,
    *,
    task_id: str = TID,
    state: str = "active",
    exe: str = "/usr/bin/mwu",
    last_error: str | None = None,
) -> None:
    st = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
    st.records.append(
        SystemTaskOperationalRecord(
            task_id=task_id,
            platform="linux",
            state=state,  # type: ignore[arg-type]
            registered_exe_path=exe,
            last_registered_at=datetime(2026, 7, 1, 12, 0, 0),
            last_error=last_error,
        )
    )
    service._memory_state = st
    service._save_state(st)


def test_operational_save_only_allowlisted_keys(service: SystemTaskService):
    st = _SystemTaskState(version=OPERATIONAL_STATE_VERSION)
    st.records.append(
        SystemTaskOperationalRecord(
            task_id="t1",
            platform="windows",
            state="active",
            registered_exe_path="/bin/mwu",
            last_registered_at=datetime(2026, 7, 1),
            last_error=None,
        )
    )
    service._save_state(st)
    data = json.loads(service._state_file.read_text(encoding="utf-8"))
    assert data["version"] == OPERATIONAL_STATE_VERSION
    assert data["version"] == 4
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
        "last_known_scope",
        "cleanup_scopes",
        "system_task_identifier",
        "warnings",
        "observed",
    ):
        assert forbidden not in reg


def test_valid_v4_load_round_trip(service: SystemTaskService):
    _seed_v4(service, state="active", exe="/bin/mwu")
    service._memory_state = None
    loaded = service._load_state()
    assert loaded.corrupt is False
    assert loaded.version == 4
    assert len(loaded.records) == 1
    assert loaded.records[0].task_id == TID
    assert loaded.records[0].state == "active"
    assert loaded.records[0].registered_exe_path == "/bin/mwu"


def test_error_state_persists(service: SystemTaskService):
    _seed_v4(service, state="error", last_error="native boom")
    service._memory_state = None
    loaded = service._load_state()
    assert loaded.records[0].state == "error"
    assert loaded.records[0].last_error == "native boom"


def test_version_mismatch_fail_closed(service: SystemTaskService):
    """v2/v3 and other versions fail closed — no migration."""
    for ver in (2, 3, 1, 99):
        service._memory_state = None
        payload = {
            "version": ver,
            "registrations": [
                {
                    "task_id": "legacy",
                    "platform": "linux",
                    "state": "active",
                }
            ],
        }
        service._state_file.write_text(json.dumps(payload), encoding="utf-8")
        st = service._load_state()
        assert st.corrupt is True, f"version {ver} must fail closed"
        assert st.records == []
        with pytest.raises(RuntimeError, match="corrupt"):
            service._save_state(st)
        # original preserved
        on_disk = json.loads(service._state_file.read_text(encoding="utf-8"))
        assert on_disk["version"] == ver


def test_malformed_current_state_fail_closed(service: SystemTaskService):
    service._state_file.write_text("{not-json", encoding="utf-8")
    service._memory_state = None
    st = service._load_state()
    assert st.corrupt is True
    with pytest.raises(RuntimeError, match="corrupt"):
        service._save_state(st)
    assert service._state_file.read_text(encoding="utf-8") == "{not-json"


def test_forbidden_keys_in_v4_fail_closed(service: SystemTaskService):
    payload = {
        "version": 4,
        "registrations": [
            {
                "task_id": "t1",
                "platform": "linux",
                "state": "active",
                "desired_scope": "user",  # forbidden mirror
            }
        ],
    }
    service._state_file.write_text(json.dumps(payload), encoding="utf-8")
    service._memory_state = None
    st = service._load_state()
    assert st.corrupt is True
    assert st.records == []


def test_atomic_replace_writes_valid_json(service: SystemTaskService):
    _seed_v4(service, task_id="a")
    assert not service._state_file.with_suffix(".json.tmp").exists()
    data = json.loads(service._state_file.read_text(encoding="utf-8"))
    assert data["version"] == 4
    assert data["registrations"][0]["task_id"] == "a"


@pytest.mark.asyncio
async def test_status_wakeup_false_authoritative(service: SystemTaskService):
    _seed_v4(service, task_id="t-off")
    task = ScheduledTask(
        id="t-off",
        name="n",
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        wakeup_enabled=False,
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=task)
    status = await service.get_status("t-off", manager=mgr)
    assert status.registered is False
    assert status.path_valid is False
    assert status.reason and "wakeup_enabled" in status.reason
    assert not hasattr(status, "observed") or getattr(status, "observed", None) is None
    assert not hasattr(status, "desired_scope") or status.model_fields.get(
        "desired_scope"
    ) is None


@pytest.mark.asyncio
async def test_status_aps_missing_not_fabricated(service: SystemTaskService):
    _seed_v4(service, task_id="t-miss")
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


@pytest.mark.asyncio
async def test_list_registered_authoritative(service: SystemTaskService):
    _seed_v4(service, task_id="t-list")
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(return_value=False),
        build_identifier=MagicMock(return_value="id"),
        verify_registration=AsyncMock(return_value=(True, "ok")),
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=None)
    regs = await service.list_registered(manager=mgr)
    assert len(regs) == 1
    assert regs[0].registered is False
    assert regs[0].path_valid is False
    assert regs[0].reason and "missing" in regs[0].reason.lower()
    # no desired_scope / observed mirrors on DTO
    assert not hasattr(regs[0], "desired_scope") or "desired_scope" not in regs[
        0
    ].model_fields

    task = ScheduledTask(
        id="t-list",
        name="live",
        enabled=True,
        trigger_type="cron",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Main"],
        wakeup_enabled=True,
    )
    mgr.get_task = AsyncMock(return_value=task)
    service._backend.is_registered = AsyncMock(return_value=True)
    regs2 = await service.list_registered(manager=mgr)
    assert regs2[0].registered is True
    assert regs2[0].task_name == "live"


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
    _seed_v4(service, task_id="t-empty-path", exe="")
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
        wakeup_enabled=True,
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=task)
    status = await service.get_status("t-empty-path", manager=mgr)
    assert status.registered is True
    assert status.verified is True
    assert status.path_valid is False


@pytest.mark.asyncio
async def test_path_valid_true_only_when_nonempty_matches(service: SystemTaskService):
    exe, _ = service.build_command_for_task("t-match")
    _seed_v4(service, task_id="t-match", exe=exe)
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
        wakeup_enabled=True,
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=task)
    status = await service.get_status("t-match", manager=mgr)
    assert status.path_valid is True

    service._backend.is_registered = AsyncMock(return_value=False)
    status2 = await service.get_status("t-match", manager=mgr)
    assert status2.registered is False
    assert status2.path_valid is False


@pytest.mark.asyncio
async def test_aps_missing_historical_native_present(service: SystemTaskService):
    _seed_v4(service, task_id="t-hist")
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(return_value=True),
        build_identifier=MagicMock(return_value="hist-id"),
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=None)
    status = await service.get_status("t-hist", manager=mgr)
    assert status.registered is False
    assert status.verified is False
    assert status.path_valid is False
    assert status.reason and "APS job missing" in status.reason
    assert "historical" in (status.reason or "").lower() or "present" in (
        status.reason or ""
    ).lower()


@pytest.mark.asyncio
async def test_aps_missing_native_unknown(service: SystemTaskService):
    _seed_v4(service, task_id="t-unk")
    service._backend = MagicMock(
        platform_name="linux",
        is_registered=AsyncMock(side_effect=RuntimeError("schtasks boom")),
        build_identifier=MagicMock(return_value="id"),
    )
    mgr = MagicMock()
    mgr.get_task = AsyncMock(return_value=None)
    status = await service.get_status("t-unk", manager=mgr)
    assert status.registered is False
    assert status.reason and "unknown" in status.reason.lower()
