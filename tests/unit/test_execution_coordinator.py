"""Unit tests for services.execution_coordinator.ExecutionCoordinator."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app_state import ActiveRun, AppState
from models.interface import InterfaceModel
from models.scheduler import (
    CronTriggerConfig,
    ManualStartPayload,
    ScheduledTask,
    ScheduledTaskDeviceConfig,
)
from services.execution_coordinator import ExecutionCoordinator, MANUAL_TASK_NAME
from services.execution_store import ExecutionStore


DEVICE = ScheduledTaskDeviceConfig(
    controller_name="ADB",
    device_type="Adb",
    device_address="127.0.0.1:5555",
)


def _manual_payload(**overrides) -> ManualStartPayload:
    data = {
        "task_list": ["Main"],
        "task_options": {"Main": {}},
        "preTasks": [],
        "controller_name": "ADB",
        "device": DEVICE,
        "resource_name": "Official",
    }
    data.update(overrides)
    return ManualStartPayload(**data)


def _scheduled(
    task_id: str = "task-1",
    name: str = "每日任务",
    *,
    cron: str = "0 9 * * *",
) -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name=name,
        trigger_config=CronTriggerConfig(cron=cron),
        task_list=["Main"],
        task_options={"Main": {}},
        controller_name="ADB",
        device=DEVICE,
        resource_name="Official",
    )


def _fake_worker():
    tasks = SimpleNamespace(
        start=MagicMock(return_value=True),
        stop=MagicMock(),
    )
    device = SimpleNamespace(
        reset_connection_state=MagicMock(),
        build_device_model_from_config=MagicMock(return_value=object()),
        connect=MagicMock(return_value=True),
        set_resource=MagicMock(return_value=True),
    )
    events = SimpleNamespace(
        send_log=MagicMock(),
        send_notification=MagicMock(),
    )
    # 真实 InterfaceModel：让 _normalize_task_payload 走完整规范化路径，
    # 而非旧的 interface=None fallback（该 fallback 静默丢弃 options/pre_tasks）。
    # task "Main" + option "difficulty"(select, default easy) 使 caller 传入的
    # 选项值能被 normalizer 原样保留，用于回归断言。
    interface = InterfaceModel.model_validate(
        {
            "interface_version": 2,
            "name": "TestGame",
            "controller": [{"name": "ADB", "type": "Adb"}],
            "resource": [{"name": "Official", "path": ["resource"]}],
            "task": [
                {
                    "name": "Main",
                    "entry": "Main",
                    "option": ["difficulty"],
                }
            ],
            "option": {
                "difficulty": {
                    "type": "select",
                    "label": "Difficulty",
                    "cases": [
                        {"name": "easy", "label": "Easy"},
                        {"name": "hard", "label": "Hard"},
                    ],
                    "default_case": "easy",
                }
            },
        }
    )
    return SimpleNamespace(
        tasks=tasks,
        device=device,
        events=events,
        interface=interface,
    )


async def _await_completion(state: AppState) -> None:
    """等待后台完成协程清理 active 槽位。"""
    task = state.active_execution_task
    if task is not None:
        await task


def _fast_retry_settings(
    *, max_retry: int = 2, retry_interval: int = 0
) -> SimpleNamespace:
    """load_settings() 替身：绕开 SettingsModel 校验，让 retryInterval 可取 0。

    _prepare_and_run 仅读取 runtime.maxRetryCount / runtime.retryInterval 与
    notification.notifyOnError，故用 SimpleNamespace 即可；真实 SettingsModel 的
    retryInterval 字段带 ge=1 校验，无法设 0，会让重试测试真实 sleep。
    """
    return SimpleNamespace(
        runtime=SimpleNamespace(
            maxRetryCount=max_retry,
            retryInterval=retry_interval,
        ),
        notification=SimpleNamespace(notifyOnError=True),
    )


@pytest.fixture
def store(tmp_path: Path) -> ExecutionStore:
    s = ExecutionStore(tmp_path / "scheduler.sqlite")
    s.init()
    return s


@pytest.fixture
def worker():
    return _fake_worker()


@pytest.fixture
def state(tmp_path: Path, worker) -> AppState:
    s = AppState(tmp_path)
    s.worker = worker
    s.device.connected = True
    s.device.configuration_locked = True
    s.device.controller_name = "ADB"
    s.device.current_resource_name = "Official"
    s.task.running = False
    s.task.last_status = "success"
    s.task.last_error = None
    return s


@pytest.fixture
def coord(store: ExecutionStore, state: AppState) -> ExecutionCoordinator:
    return ExecutionCoordinator(state, store)


@pytest.mark.asyncio
async def test_manual_manual_conflict_busy_manual(
    coord: ExecutionCoordinator, state: AppState, store
):
    state.active_run = ActiveRun(
        run_id="active-manual",
        origin="manual",
        task_name=MANUAL_TASK_NAME,
        occurrence_id=None,
    )
    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is False
    assert result.conflict is not None
    assert result.conflict.code == "busy_manual"
    assert result.conflict.active_run_id == "active-manual"
    assert result.conflict.active_task_name == MANUAL_TASK_NAME
    assert "手动" in result.conflict.message
    assert store.list() == []


@pytest.mark.asyncio
async def test_scheduled_while_manual_skipped_busy_manual(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore
):
    state.active_run = ActiveRun(
        run_id="m1",
        origin="manual",
        task_name=MANUAL_TASK_NAME,
        occurrence_id=None,
    )
    result = await coord.submit_scheduled(_scheduled(), origin="in_app")
    assert result.accepted is False
    assert result.skip_status == "skipped_busy_manual"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "skipped_busy_manual"
    assert rows[0].blocker_run_id == "m1"
    assert rows[0].blocker_task_name == MANUAL_TASK_NAME


@pytest.mark.asyncio
async def test_manual_while_scheduled_conflict_busy_scheduled(
    coord: ExecutionCoordinator, state: AppState
):
    state.active_run = ActiveRun(
        run_id="s1",
        origin="in_app",
        task_name="定时甲",
        occurrence_id="occ",
    )
    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is False
    assert result.conflict is not None
    assert result.conflict.code == "busy_scheduled"
    assert result.conflict.active_task_name == "定时甲"
    assert "定时" in result.conflict.message


@pytest.mark.asyncio
async def test_two_scheduled_different_tasks_skipped_busy_scheduled(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore
):
    state.active_run = ActiveRun(
        run_id="s1",
        origin="in_app",
        task_name="任务A",
        occurrence_id="a:occ",
    )
    result = await coord.submit_scheduled(
        _scheduled(task_id="task-b", name="任务B"), origin="in_app"
    )
    assert result.accepted is False
    assert result.skip_status == "skipped_busy_scheduled"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "skipped_busy_scheduled"
    assert rows[0].blocker_task_name == "任务A"


@pytest.mark.asyncio
async def test_update_gate_manual_conflict_and_scheduled_skip(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore
):
    state.update_in_progress = True

    manual = await coord.submit_manual(_manual_payload())
    assert manual.accepted is False
    assert manual.conflict is not None
    assert manual.conflict.code == "update_in_progress"
    assert "更新" in manual.conflict.message

    scheduled = await coord.submit_scheduled(_scheduled(), origin="in_app")
    assert scheduled.accepted is False
    assert scheduled.skip_status == "skipped_update_in_progress"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "skipped_update_in_progress"


@pytest.mark.asyncio
async def test_manual_admission_immediate_while_execution_active(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore, monkeypatch
):
    """入场立即返回；执行仍在后台活跃时可再次冲突。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_prepare(**kwargs):
        del kwargs
        started.set()
        await release.wait()
        return "success", None

    monkeypatch.setattr(coord, "_prepare_and_run", slow_prepare)

    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    assert result.run_id is not None
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert state.active_run is not None
    assert state.active_run.run_id == result.run_id
    assert state.active_execution_task is not None
    assert not state.active_execution_task.done()

    # 执行中写入 running 行
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "running"

    # 二次入场冲突
    conflict = await coord.submit_manual(_manual_payload())
    assert conflict.accepted is False
    assert conflict.conflict is not None
    assert conflict.conflict.code == "busy_manual"

    release.set()
    await _await_completion(state)
    assert state.active_run is None
    assert state.active_execution_task is None
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].finished_at is not None


@pytest.mark.asyncio
async def test_manual_success_writes_origin_manual(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore, worker
):
    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    assert result.run_id is not None
    await _await_completion(state)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].origin == "manual"
    assert rows[0].task_name == MANUAL_TASK_NAME
    assert rows[0].task_id is None
    assert rows[0].status == "success"
    assert rows[0].finished_at is not None
    worker.tasks.start.assert_called_once()
    assert coord.active_run() is None
    assert state.active_execution_task is None


@pytest.mark.asyncio
async def test_store_add_failure_clears_active_run(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore, monkeypatch
):
    """store.add 失败时清 active_run 并向上抛出。"""

    def boom(*_args, **_kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(store, "add", boom)
    with pytest.raises(RuntimeError, match="db write failed"):
        await coord.submit_manual(_manual_payload())
    assert state.active_run is None
    assert state.active_execution_task is None


@pytest.mark.asyncio
async def test_native_late_missed_deadline(
    coord: ExecutionCoordinator, store: ExecutionStore, monkeypatch
):
    now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    occurrence = now - timedelta(minutes=20)

    monkeypatch.setattr(
        "services.execution_coordinator._local_now",
        lambda: now.astimezone(),
    )
    monkeypatch.setattr(
        "services.execution_coordinator._utc_now",
        lambda: now,
    )
    monkeypatch.setattr(
        "services.execution_coordinator.compute_occurrence",
        lambda trigger, n: occurrence,
    )

    result = await coord.submit_scheduled(_scheduled(), origin="native")
    assert result.accepted is False
    assert result.skip_status == "missed_deadline"
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "missed_deadline"
    assert rows[0].origin == "native"
    assert rows[0].finished_at is not None
    result2 = await coord.submit_scheduled(_scheduled(), origin="native")
    assert result2.skip_status == "missed_deadline"
    assert len(store.list()) == 2


@pytest.mark.asyncio
async def test_stop_active_waits_then_restart_possible(
    coord: ExecutionCoordinator, state: AppState, worker, monkeypatch
):
    """stop 等待后台清理完成后可再次启动。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_prepare(**kwargs):
        del kwargs
        started.set()
        await release.wait()
        return "stopped", "任务已终止"

    monkeypatch.setattr(coord, "_prepare_and_run", slow_prepare)

    first = await coord.submit_manual(_manual_payload())
    assert first.accepted is True
    await asyncio.wait_for(started.wait(), timeout=1.0)

    async def release_soon():
        await asyncio.sleep(0.05)
        release.set()

    asyncio.create_task(release_soon())
    stopped = await coord.stop_active()
    assert stopped is True
    worker.tasks.stop.assert_called_once()
    assert state.active_run is None
    assert state.active_execution_task is None

    # 清理后可再次入场
    second = await coord.submit_manual(_manual_payload())
    assert second.accepted is True
    await _await_completion(state)
    assert state.active_run is None


@pytest.mark.asyncio
async def test_stop_during_prepare_returns_stopped(
    coord: ExecutionCoordinator,
    state: AppState,
    store: ExecutionStore,
    worker,
    monkeypatch,
):
    """prepare 阶段 stop_requested 则返回 stopped，不启动任务。"""
    original_prepare = coord._prepare_and_run

    async def prepare_with_stop(**kwargs):
        # 模拟 setup 中途被 stop
        active = state.active_run
        assert active is not None
        active.stop_requested = True
        return await original_prepare(**kwargs)

    monkeypatch.setattr(coord, "_prepare_and_run", prepare_with_stop)

    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    await _await_completion(state)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "stopped"
    # 因 stop 在 start 前返回，tasks.start 不应被调用
    worker.tasks.start.assert_not_called()


@pytest.mark.asyncio
async def test_stop_active_no_run_returns_false(coord: ExecutionCoordinator, worker):
    assert await coord.stop_active() is False
    worker.tasks.stop.assert_not_called()


@pytest.mark.asyncio
async def test_in_app_success_path(
    coord: ExecutionCoordinator, state: AppState, store: ExecutionStore, monkeypatch
):
    fixed = datetime(2026, 7, 19, 9, 2, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "services.execution_coordinator._local_now",
        lambda: fixed.astimezone(),
    )
    monkeypatch.setattr(
        "services.execution_coordinator._utc_now",
        lambda: fixed,
    )
    monkeypatch.setattr(
        "services.execution_coordinator.compute_occurrence",
        lambda trigger, now: fixed.replace(minute=0, second=0, microsecond=0),
    )
    result = await coord.submit_scheduled(_scheduled(), origin="in_app")
    assert result.accepted is True
    await _await_completion(state)
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].origin == "in_app"
    assert rows[0].status == "success"
    assert rows[0].occurrence_id is not None
    assert coord.active_run() is None


@pytest.mark.asyncio
async def test_manual_passes_caller_task_options_to_worker(
    coord: ExecutionCoordinator, state: AppState, worker
):
    """caller 的 task_options 必须原样送达 worker.tasks.start。

    回归：旧 _normalize_task_payload 在 interface=None 时走 fallback，无条件返回
    {tid: {} for tid in ...}，丢弃全部 options/pre_tasks —— 导致以默认值静默执行。
    现在无条件走完整 normalizer，caller 传入且被 interface 认可的选项值必须保留。
    """
    custom_options = {"Main": {"difficulty": "hard"}}
    result = await coord.submit_manual(_manual_payload(task_options=custom_options))
    assert result.accepted is True
    await _await_completion(state)
    worker.tasks.start.assert_called_once()
    # worker.tasks.start(task_list, task_options, task_name=..., pre_tasks=...)
    sent_task_options = worker.tasks.start.call_args.args[1]
    assert sent_task_options == custom_options


@pytest.mark.asyncio
async def test_retry_resets_state_when_set_resource_returns_false(
    coord: ExecutionCoordinator,
    state: AppState,
    store: ExecutionStore,
    worker,
    monkeypatch,
):
    """回归：connect 成功但 set_resource 返回 False 时，重试前必须 reset。

    缺陷：旧实现 except handler 只 sleep+log，不清 connected=True 的残留 controller，
    下次 connect 新建的 controller 拿不到事件 sink（register_controller_sink 因
    _controller_sink_id 仍被占用提前返回），控制器侧事件静默丢失。
    修复：except handler 顶部无条件 await reset_connection_state。
    本测试让 attempt 1 的 set_resource 返回 False、attempt 2 返回 True，断言两次
    attempt 之间存在 reset_connection_state——缺陷版本会缺失这一步。
    """
    # 强制 need_connect=True，让重试循环真正被执行
    # （默认 fixture 用 connected=True+configuration_locked=True 复用连接，循环不进入）
    state.device.connected = False
    state.device.configuration_locked = False

    monkeypatch.setattr(
        "services.execution_coordinator.load_settings",
        lambda: _fast_retry_settings(max_retry=2),
    )

    call_log: list[str] = []
    set_resource_invocations = 0

    def _connect(_model):
        call_log.append("connect")
        return True

    def _set_resource(_name):
        nonlocal set_resource_invocations
        set_resource_invocations += 1
        call_log.append("set_resource")
        # 第一次返回 False（触发 except），第二次返回 True
        return False if set_resource_invocations == 1 else True

    def _reset():
        call_log.append("reset_connection_state")

    worker.device.connect = MagicMock(side_effect=_connect)
    worker.device.set_resource = MagicMock(side_effect=_set_resource)
    worker.device.reset_connection_state = MagicMock(side_effect=_reset)

    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    await _await_completion(state)

    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "success"

    # 完整调用次序（含 pre-loop 无条件 reset）：
    #   reset(pre-loop) → connect(1) → set_resource(1, False) →
    #   reset(except handler, 即修复 #2) → connect(2) → set_resource(2, True)
    # 关键回归点：两次 attempt 之间存在 reset_connection_state。
    # 缺陷版本（移除 except handler 的 reset）→ 次序变为
    #   [reset, connect, set_resource, connect, set_resource]，断言失败。
    assert call_log == [
        "reset_connection_state",
        "connect",
        "set_resource",
        "reset_connection_state",
        "connect",
        "set_resource",
    ]


@pytest.mark.asyncio
async def test_retry_resets_state_when_set_resource_raises(
    coord: ExecutionCoordinator,
    state: AppState,
    store: ExecutionStore,
    worker,
    monkeypatch,
):
    """set_resource 抛异常时，重试前同样必须 reset（与返回 False 等价路径）。"""
    state.device.connected = False
    state.device.configuration_locked = False

    monkeypatch.setattr(
        "services.execution_coordinator.load_settings",
        lambda: _fast_retry_settings(max_retry=2),
    )

    call_log: list[str] = []
    set_resource_invocations = 0

    def _connect(_model):
        call_log.append("connect")
        return True

    def _set_resource(_name):
        nonlocal set_resource_invocations
        set_resource_invocations += 1
        call_log.append("set_resource")
        # 第一次抛异常，第二次成功
        if set_resource_invocations == 1:
            raise RuntimeError("set_resource boom")
        return True

    def _reset():
        call_log.append("reset_connection_state")

    worker.device.connect = MagicMock(side_effect=_connect)
    worker.device.set_resource = MagicMock(side_effect=_set_resource)
    worker.device.reset_connection_state = MagicMock(side_effect=_reset)

    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    await _await_completion(state)

    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "success"

    # 与 test_retry_resets_state_when_set_resource_returns_false 相同期望：
    # 失败路径无论是返回 False 还是抛异常，except handler 都必须先 reset 再重试。
    assert call_log == [
        "reset_connection_state",
        "connect",
        "set_resource",
        "reset_connection_state",
        "connect",
        "set_resource",
    ]


@pytest.mark.asyncio
async def test_happy_path_no_extra_reset_in_except(
    coord: ExecutionCoordinator,
    state: AppState,
    store: ExecutionStore,
    worker,
    monkeypatch,
):
    """成功路径：except handler 不执行，不应有额外 reset。

    注意：need_connect=True 时 pre-loop（修复 #1）仍会无条件 reset 一次，故期望
    total==1 而非 assert_not_called()。此 pre-loop reset 与 except reset 是两处
    不同调用点，勿混淆。
    """
    state.device.connected = False
    state.device.configuration_locked = False

    monkeypatch.setattr(
        "services.execution_coordinator.load_settings",
        lambda: _fast_retry_settings(max_retry=2),
    )

    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    await _await_completion(state)

    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "success"

    # connect+set_resource 首次即成功 → except 不进入 → 仅 pre-loop 那 1 次 reset。
    # fixture 默认 connect/set_resource 均 return_value=True，无需覆盖。
    # 1 次 = pre-loop 无条件 reset；except handler 的 reset（修复 #2）未触发。
    assert worker.device.reset_connection_state.call_count == 1


@pytest.mark.asyncio
async def test_retry_exhausted_returns_failed_and_resets(
    coord: ExecutionCoordinator,
    state: AppState,
    store: ExecutionStore,
    worker,
    monkeypatch,
):
    """set_resource 始终失败且重试耗尽：返回 failed + 设备连接失败，状态被清理。"""
    state.device.connected = False
    state.device.configuration_locked = False

    monkeypatch.setattr(
        "services.execution_coordinator.load_settings",
        lambda: _fast_retry_settings(max_retry=2),
    )

    # set_resource 始终返回 False → connect 成功但每次 raise → 重试耗尽
    worker.device.set_resource = MagicMock(return_value=False)

    result = await coord.submit_manual(_manual_payload())
    assert result.accepted is True
    await _await_completion(state)

    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error_message == "设备连接失败"

    # 状态被清理：post-loop reset（耗尽路径的关键清理点）必被调用。
    # 修复后总计 4 次：pre-loop(1) + except×2 + post-loop(1)；此处只断言「被清理」，
    # 不绑定 except 的 reset 计数（那是 (a)/(b) 的回归点），保持本测试聚焦于耗尽终态。
    assert worker.device.reset_connection_state.called


@pytest.mark.asyncio
async def test_complete_run_cancelled_writes_stopped_and_reraises(
    coord: ExecutionCoordinator,
    state: AppState,
    store: ExecutionStore,
    monkeypatch,
):
    """_complete_run 被 task.cancel() 取消时：shield 保护 store.finish(stopped, 任务被取消)
    写入完成，CancelledError 继续向 awaiter 传播，且 finally 清空 active 槽位。

    回归：except CancelledError 是 finally 之前唯一能落终态的窗口，否则 DB 行残留
    running。shield(finish) 保证取消期间 finish 写入本身不被二次取消破坏。
    """
    started = asyncio.Event()
    block_prepare = asyncio.Event()

    async def blocking_prepare(**kwargs):
        del kwargs
        started.set()
        await block_prepare.wait()
        return "success", None  # 不可达

    monkeypatch.setattr(coord, "_prepare_and_run", blocking_prepare)

    adm = await coord.submit_manual(_manual_payload())
    assert adm.accepted and adm.run_id is not None
    await asyncio.wait_for(started.wait(), timeout=1.0)

    task = state.active_execution_task
    assert task is not None and not task.done()

    # 模拟外部 cancel（lifespan teardown 路径或显式取消）
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # 终态写入：stopped + 任务被取消
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "stopped"
    assert rows[0].error_message == "任务被取消"
    assert rows[0].finished_at is not None

    # finally 清理 active 槽位
    assert state.active_run is None
    assert state.active_execution_task is None


def _dead_thread() -> threading.Thread:
    """构造一个已死亡的线程，用于 stale thread 收敛回归。"""
    t = threading.Thread(target=lambda: None, name="mwu-test-dead-thread")
    t.start()
    t.join()
    return t


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stale_thread_kind",
    [pytest.param("missing", id="missing"), pytest.param("dead", id="dead")],
)
async def test_prepare_and_run_converges_stale_thread_as_failed(
    stale_thread_kind: str,
    coord: ExecutionCoordinator,
    state: AppState,
    store: ExecutionStore,
    worker,
):
    """stale 状态回归：running=True 但 thread 缺失/已死 时循环必须收敛，而非永久等待。

    旧行为 `while task_state.running: sleep` 在 thread 缺失/已死 + running 残留
    时永久阻塞。修复后检测到 stale 立即落 failed/任务执行线程异常退出，
    并清 running/thread 让后续启动不再被阻塞。固定终态为 failed。
    """
    state.task.thread = None if stale_thread_kind == "missing" else _dead_thread()
    state.task.running = True
    # 非终态 last_status：触发收敛分支写入 failed/任务执行线程异常退出
    state.task.last_status = "idle"
    state.task.last_error = None

    adm = await coord.submit_manual(_manual_payload())
    assert adm.accepted
    await _await_completion(state)

    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].error_message == "任务执行线程异常退出"
    assert rows[0].finished_at is not None

    # 残留状态被清理：后续启动不再被 running=True + dead thread 阻塞
    assert state.task.running is False
    assert state.task.thread is None
    assert state.active_run is None
    assert state.active_execution_task is None
    worker.tasks.start.assert_called_once()


@pytest.mark.asyncio
async def test_stop_active_timeout_does_not_cancel_completion(
    coord: ExecutionCoordinator,
    state: AppState,
    worker,
):
    """stop_active 被 main.py wait_for 超时取消时，completion task 不被连带取消。

    回归要点：`await asyncio.shield(completion)` 确保取消停止逻辑不会传递给
    completion 本身——否则 _complete_run 的 CancelledError 处理会提前写 stopped
    并清槽位，而底层 MAA 线程仍活。这里验证"取消 stop_active 不取消 completion"。
    模拟 main.py:375 `wait_for(stop_active, timeout=15)`，用极短 timeout 触发超时。
    """
    release = asyncio.Event()

    async def slow_completion():
        await release.wait()

    completion = asyncio.create_task(slow_completion())
    state.active_execution_task = completion
    state.active_run = ActiveRun(
        run_id="shield-run",
        origin="manual",
        task_name=MANUAL_TASK_NAME,
        occurrence_id=None,
    )

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(coord.stop_active(), timeout=0.05)

    # shield 保护：completion 未被取消，仍在 pending
    assert not completion.cancelled()
    assert not completion.done()
    worker.tasks.stop.assert_called_once()

    # 释放后自然完成，无异常
    release.set()
    await asyncio.wait_for(completion, timeout=1.0)
    assert completion.done()
    assert not completion.cancelled()

    state.active_run = None
    state.active_execution_task = None
