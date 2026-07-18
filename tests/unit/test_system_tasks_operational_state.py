"""Operational state v4 schema: load/save allowlist, fail-closed."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import json_utils as json
from models.scheduler import (
    OPERATIONAL_STATE_KEYS,
    OPERATIONAL_STATE_VERSION,
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


def test_malformed_current_state_fail_closed(service: SystemTaskService):
    service._state_file.write_text("{not-json", encoding="utf-8")
    service._memory_state = None
    st = service._load_state()
    assert st.corrupt is True
    with pytest.raises(RuntimeError, match="corrupt"):
        service._save_state(st)
    assert service._state_file.read_text(encoding="utf-8") == "{not-json"


def test_atomic_replace_writes_valid_json(service: SystemTaskService):
    _seed_v4(service, task_id="a")
    assert not service._state_file.with_suffix(".json.tmp").exists()
    data = json.loads(service._state_file.read_text(encoding="utf-8"))
    assert data["version"] == 4
    assert data["registrations"][0]["task_id"] == "a"
