"""API-level tests for Lane D scheduler wiring (TestClient + stubs)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


def _wakeup_task(
    task_id: str = "task-1",
    *,
    enabled: bool = True,
    wakeup_enabled: bool = True,
) -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name="每日",
        enabled=enabled,
        wakeup_enabled=wakeup_enabled,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Startup"],
    )


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


def test_native_dispatch_disabled_409(client):
    c, main = client
    main.app_state.native_token = "tok"
    task = _wakeup_task(enabled=False, wakeup_enabled=True)
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    coord = SimpleNamespace(submit_scheduled=AsyncMock())
    main.app_state.scheduler_manager = manager
    main.app_state.execution_coordinator = coord

    resp = c.post(
        "/api/internal/scheduler/native-dispatch",
        json={"task_id": "task-1", "token": "tok"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["status"] == "failed"
    coord.submit_scheduled.assert_not_called()


def test_native_dispatch_wakeup_disabled_409(client):
    c, main = client
    main.app_state.native_token = "tok"
    task = _wakeup_task(enabled=True, wakeup_enabled=False)
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    coord = SimpleNamespace(submit_scheduled=AsyncMock())
    main.app_state.scheduler_manager = manager
    main.app_state.execution_coordinator = coord

    resp = c.post(
        "/api/internal/scheduler/native-dispatch",
        json={"task_id": "task-1", "token": "tok"},
    )
    assert resp.status_code == 409
    assert resp.json()["status"] == "failed"
    coord.submit_scheduled.assert_not_called()


def test_native_dispatch_ok_calls_submit_scheduled(client):
    c, main = client
    main.app_state.native_token = "tok"
    task = _wakeup_task()
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
    assert "deduplicated" not in data
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
    store = SimpleNamespace(list=MagicMock(return_value=rows))
    main.app_state.execution_store = store

    resp = c.get("/api/scheduler/executions?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert len(data["executions"]) == 1
    assert data["executions"][0]["id"] == "e1"
    assert data["executions"][0]["origin"] == "manual"
    store.list.assert_called_once_with(10)


def test_start_success_returns_run_id(client):
    c, main = client
    coord = SimpleNamespace(
        submit_manual=AsyncMock(return_value=Admission(accepted=True, run_id="run-ok"))
    )
    main.app_state.execution_coordinator = coord
    resp = c.post("/api/start", json=_manual_body())
    assert resp.status_code == 200
    assert resp.json() == {"status": "success", "run_id": "run-ok"}


def test_delegate_native_dispatch_2xx_success(main_module, tmp_path, monkeypatch):
    token_file = tmp_path / "native_token"
    token_file.write_text("tok", encoding="utf-8")
    monkeypatch.setattr(main_module, "NATIVE_TOKEN_FILE", token_file)

    class _Resp:
        status_code = 200
        text = "ok"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            return _Resp()

    monkeypatch.setattr(main_module.httpx, "Client", _Client)
    assert main_module.delegate_native_dispatch("t1") == main_module.EXIT_SUCCESS


def test_delegate_native_dispatch_4xx_failed(main_module, tmp_path, monkeypatch):
    token_file = tmp_path / "native_token"
    token_file.write_text("tok", encoding="utf-8")
    monkeypatch.setattr(main_module, "NATIVE_TOKEN_FILE", token_file)

    class _Resp:
        status_code = 409
        text = "conflict"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            return _Resp()

    monkeypatch.setattr(main_module.httpx, "Client", _Client)
    assert (
        main_module.delegate_native_dispatch("t1") == main_module.EXIT_DELEGATE_FAILED
    )


def test_delegate_native_dispatch_retry_exhaustion(main_module, tmp_path, monkeypatch):
    token_file = tmp_path / "native_token"
    token_file.write_text("tok", encoding="utf-8")
    monkeypatch.setattr(main_module, "NATIVE_TOKEN_FILE", token_file)

    class _Resp:
        status_code = 503
        text = "busy"

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            return _Resp()

    # 跳过真实 sleep / 缩短截止
    monkeypatch.setattr(main_module.httpx, "Client", _Client)
    monkeypatch.setattr(main_module.time, "sleep", lambda *_: None)
    times = iter([0.0, 0.0, 40.0])  # 第一次循环后立即超时
    monkeypatch.setattr(main_module.time, "monotonic", lambda: next(times, 40.0))
    assert (
        main_module.delegate_native_dispatch("t1") == main_module.EXIT_DELEGATE_FAILED
    )
