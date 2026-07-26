"""API-level tests for Lane D scheduler wiring (TestClient + stubs)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
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
from services.process_lock import (
    LockBusyError,
    LockPermissionError,
    UpdateLockBusyError,
)


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


def test_native_dispatch_rejected_returns_409(client):
    """入场被拒（冲突/迟到/忙）时返回 409，使 CLI 委托映射到非零退出码。"""
    c, main = client
    main.app_state.native_token = "tok"
    task = _wakeup_task()
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    coord = SimpleNamespace(
        submit_scheduled=AsyncMock(
            return_value=Admission(
                accepted=False,
                run_id="run-skip",
                skip_status="skipped_busy_manual",
            )
        )
    )
    main.app_state.scheduler_manager = manager
    main.app_state.execution_coordinator = coord

    resp = c.post(
        "/api/internal/scheduler/native-dispatch",
        json={"task_id": "task-1", "token": "tok"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["status"] == "failed"
    assert data["accepted"] is False
    assert data["skip_status"] == "skipped_busy_manual"
    assert data["run_id"] == "run-skip"
    assert "skipped_busy_manual" in data["message"]
    # conflict 字段始终存在（scheduled 路径下为 None），便于前端统一处理
    assert "conflict" in data
    coord.submit_scheduled.assert_awaited_once()


def test_native_dispatch_rejected_missed_deadline_409(client):
    """迟到超 misfire 窗口同样返回 409，并携带 skip_status=missed_deadline。"""
    c, main = client
    main.app_state.native_token = "tok"
    task = _wakeup_task()
    manager = SimpleNamespace(get_task=AsyncMock(return_value=task))
    coord = SimpleNamespace(
        submit_scheduled=AsyncMock(
            return_value=Admission(
                accepted=False,
                run_id="run-md",
                skip_status="missed_deadline",
            )
        )
    )
    main.app_state.scheduler_manager = manager
    main.app_state.execution_coordinator = coord

    resp = c.post(
        "/api/internal/scheduler/native-dispatch",
        json={"task_id": "task-1", "token": "tok"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["status"] == "failed"
    assert data["skip_status"] == "missed_deadline"
    assert data["conflict"] is None
    coord.submit_scheduled.assert_awaited_once()


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


@pytest.mark.parametrize(
    ("exc", "scheduled_task", "expected_code", "expected_msg"),
    [
        # UpdateLockBusyError（LockBusyError 子类）必须优先匹配 → exit 5，
        # 即便有定时任务也不委托（更新进行中，无可委托对象）
        pytest.param(
            UpdateLockBusyError("update held"),
            None,
            5,
            "更新进行中，无法启动",
            id="update-busy-no-task",
        ),
        pytest.param(
            UpdateLockBusyError("update held"),
            "task-1",
            5,
            "更新进行中，无法启动",
            id="update-busy-with-task",
        ),
        # 普通 LockBusyError（runtime 锁被占）：无定时任务 → exit 4
        pytest.param(
            LockBusyError("runtime held"),
            None,
            4,
            "应用已在运行",
            id="runtime-busy-no-task",
        ),
        # LockPermissionError / 其他 LockError → 协议失败 exit 5
        pytest.param(
            LockPermissionError("denied"),
            None,
            5,
            "锁协议失败:",
            id="permission-no-task",
        ),
        pytest.param(
            LockPermissionError("denied"),
            "task-1",
            5,
            "锁协议失败:",
            id="permission-with-task",
        ),
    ],
)
def test_handle_startup_lock_error_exit_codes(
    main_module, capsys, exc, scheduled_task, expected_code, expected_msg
):
    """按异常类型固定启动退出码，替代 str(e).lower() 字面耦合。

    覆盖顺序敏感性：update-busy-with-task 仍为 5 而非委托——这正向验证
    UpdateLockBusyError（子类）先于普通 LockBusyError 匹配。
    """
    with pytest.raises(SystemExit) as exc_info:
        main_module.handle_startup_lock_error(exc, scheduled_task)
    assert exc_info.value.code == expected_code
    assert expected_msg in capsys.readouterr().out


def test_handle_startup_lock_error_delegates_runtime_busy(main_module, monkeypatch):
    """runtime 锁被占且有 scheduled_task → 委托给运行中实例。

    monkeypatch delegate_native_dispatch 返回 1；断言其收到 scheduled_task
    且 helper sys.exit 该返回码。
    """
    calls: list[str] = []

    def _fake_dispatch(task_id: str) -> int:
        calls.append(task_id)
        return 1

    monkeypatch.setattr(main_module, "delegate_native_dispatch", _fake_dispatch)

    with pytest.raises(SystemExit) as exc_info:
        main_module.handle_startup_lock_error(LockBusyError("runtime held"), "task-9")
    assert exc_info.value.code == 1
    assert calls == ["task-9"]


def _stub_token_paths(main_module, tmp_path: Path, monkeypatch) -> Path:
    """把 main 模块的 CONFIG_DIR / NATIVE_TOKEN_FILE 重定向到 tmp_path。"""
    monkeypatch.setattr(main_module, "CONFIG_DIR", tmp_path)
    token_file = tmp_path / "native_token"
    monkeypatch.setattr(main_module, "NATIVE_TOKEN_FILE", token_file)
    return token_file


@pytest.mark.parametrize(
    "blank_content",
    [
        pytest.param("", id="empty"),
        pytest.param("\n\n   \t", id="mixed-whitespace"),
    ],
)
def test_ensure_native_token_regenerates_when_blank(
    main_module, tmp_path, monkeypatch, blank_content
):
    """存在但内容为空/仅空白的 token 文件视为损坏：重新生成并覆盖写回。"""
    token_file = _stub_token_paths(main_module, tmp_path, monkeypatch)
    token_file.write_text(blank_content, encoding="utf-8")

    token = main_module.ensure_native_token()
    # 重新生成：非空、合法 hex、已覆盖写回文件
    assert token
    assert len(token) == 64  # secrets.token_hex(32) → 64 hex chars
    assert all(c in "0123456789abcdef" for c in token)
    assert token_file.read_text(encoding="utf-8").strip() == token


def test_ensure_native_token_reuses_valid(main_module, tmp_path, monkeypatch):
    """有效 token（strip 后非空）原样读取，不重写文件。"""
    token_file = _stub_token_paths(main_module, tmp_path, monkeypatch)
    raw = "  deadbeefcafef00d  \n"
    token_file.write_text(raw, encoding="utf-8")

    token = main_module.ensure_native_token()
    assert token == "deadbeefcafef00d"
    # 未重写文件：内容保持原样
    assert token_file.read_text(encoding="utf-8") == raw
