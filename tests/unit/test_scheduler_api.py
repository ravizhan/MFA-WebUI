"""API-level tests for Lane D scheduler wiring (TestClient + stubs)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from models.scheduler import (
    CronTriggerConfig,
    ScheduledTask,
    StartConflict,
    TaskExecution,
)
from services.execution_coordinator import Admission


@pytest.fixture
def client(main_module):
    """TestClient without real lifespan (no APS/DB/MaaWorker)."""

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    # Starlette stores the lifespan context on the router.
    main_module.app.router.lifespan_context = noop_lifespan
    with TestClient(main_module.app, raise_server_exceptions=False) as c:
        yield c, main_module


def _manual_body(**overrides) -> dict:
    body = {
        "task_list": ["Startup"],
        "task_options": {},
        "preTasks": [],
        "controller_name": "ADB",
        "device": {
            "controller_name": "ADB",
            "device_type": "Adb",
            "device_address": "127.0.0.1:5555",
        },
        "resource_name": "main",
    }
    body.update(overrides)
    return body


def test_start_returns_conflict_structure(client):
    c, main = client
    conflict = StartConflict(
        code="busy_manual",
        message="当前有手动任务「手动执行」正在执行",
        active_run_id="run-active",
        active_task_name="手动执行",
        active_origin="manual",
    )
    coord = SimpleNamespace(
        submit_manual=AsyncMock(
            return_value=Admission(accepted=False, conflict=conflict)
        )
    )
    main.app_state.execution_coordinator = coord

    resp = c.post("/api/start", json=_manual_body())
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "conflict"
    assert data["conflict"]["code"] == "busy_manual"
    assert data["conflict"]["active_run_id"] == "run-active"
    assert data["conflict"]["active_task_name"] == "手动执行"
    assert data["conflict"]["active_origin"] == "manual"
    coord.submit_manual.assert_awaited_once()


def test_native_dispatch_wrong_token_401(client):
    c, main = client
    main.app_state.native_token = "correct-token"
    main.app_state.scheduler_manager = SimpleNamespace()
    main.app_state.execution_coordinator = SimpleNamespace()

    resp = c.post(
        "/api/internal/scheduler/native-dispatch",
        json={"task_id": "t1", "token": "wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["status"] == "failed"


def test_native_dispatch_task_not_found_404(client):
    c, main = client
    main.app_state.native_token = "tok"
    main.app_state.scheduler_manager = SimpleNamespace(
        get_task=AsyncMock(return_value=None)
    )
    main.app_state.execution_coordinator = SimpleNamespace(submit_scheduled=AsyncMock())

    resp = c.post(
        "/api/internal/scheduler/native-dispatch",
        json={"task_id": "missing", "token": "tok"},
    )
    assert resp.status_code == 404
    main.app_state.execution_coordinator.submit_scheduled.assert_not_called()


def test_native_dispatch_ok_calls_submit_scheduled(client):
    c, main = client
    main.app_state.native_token = "tok"
    task = ScheduledTask(
        id="task-1",
        name="每日",
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Startup"],
    )
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    coord = SimpleNamespace(
        submit_scheduled=AsyncMock(
            return_value=Admission(accepted=True, run_id="run-n1")
        )
    )
    main.app_state.scheduler_manager = manager
    main.app_state.execution_coordinator = coord

    resp = c.post(
        "/api/internal/scheduler/native-dispatch",
        json={"task_id": "task-1", "token": "tok"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["accepted"] is True
    assert data["run_id"] == "run-n1"
    assert data["deduplicated"] is False
    coord.submit_scheduled.assert_awaited_once()
    args, kwargs = coord.submit_scheduled.await_args
    assert args[0].id == "task-1"
    assert kwargs.get("origin") == "native" or (len(args) > 1 and args[1] == "native")


def test_create_wakeup_non_cron_400(client):
    c, main = client
    manager = SimpleNamespace(
        create_task=AsyncMock(
            side_effect=ValueError("wakeup_enabled 仅支持 cron 触发器")
        )
    )
    main.app_state.scheduler_manager = manager

    body = {
        "name": "interval-wakeup",
        "enabled": True,
        "wakeup_enabled": True,
        "trigger_config": {"type": "interval", "hours": 1},
        "task_list": ["Startup"],
        "task_options": {},
        "preTasks": [],
    }
    resp = c.post("/api/scheduler/tasks", json=body)
    assert resp.status_code == 400
    assert resp.json()["status"] == "failed"
    assert "wakeup" in resp.json()["message"] or "cron" in resp.json()["message"]


def test_create_wakeup_illegal_cron_400(client):
    c, main = client
    manager = SimpleNamespace(
        create_task=AsyncMock(
            side_effect=ValueError("native cron 不支持 list/range/step")
        )
    )
    main.app_state.scheduler_manager = manager

    body = {
        "name": "bad-cron",
        "enabled": True,
        "wakeup_enabled": True,
        "trigger_config": {"type": "cron", "cron": "*/5 * * * *"},
        "task_list": ["Startup"],
        "task_options": {},
        "preTasks": [],
    }
    resp = c.post("/api/scheduler/tasks", json=body)
    assert resp.status_code == 400
    assert resp.json()["status"] == "failed"


def test_get_executions_from_store(client):
    c, main = client
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    rows = [
        TaskExecution(
            id="e1",
            task_id=None,
            task_name="手动执行",
            origin="manual",
            status="success",
            started_at=now,
            finished_at=now,
        )
    ]
    store = SimpleNamespace(list=AsyncMock(return_value=rows))
    main.app_state.execution_store = store

    resp = c.get("/api/scheduler/executions?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["executions"]) == 1
    assert data["executions"][0]["id"] == "e1"
    assert data["executions"][0]["origin"] == "manual"
    store.list.assert_awaited_once_with(10)


def test_start_success_returns_run_id(client):
    c, main = client
    coord = SimpleNamespace(
        submit_manual=AsyncMock(return_value=Admission(accepted=True, run_id="run-ok"))
    )
    main.app_state.execution_coordinator = coord
    resp = c.post("/api/start", json=_manual_body())
    assert resp.status_code == 200
    assert resp.json() == {"status": "success", "run_id": "run-ok"}
