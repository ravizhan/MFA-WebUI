"""Lifespan teardown: wait for active execution before worker shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app_state import AppState
from models.scheduler import ManualStartPayload, ScheduledTaskDeviceConfig
from services.execution_coordinator import ExecutionCoordinator
from services.execution_store import ExecutionStore


DEVICE = ScheduledTaskDeviceConfig(
    controller_name="ADB",
    device_type="Adb",
    device_address="127.0.0.1:5555",
)


def _manual_payload() -> ManualStartPayload:
    return ManualStartPayload(
        task_list=["Main"],
        task_options={"Main": {}},
        preTasks=[],
        controller_name="ADB",
        device=DEVICE,
        resource_name="Official",
    )


@pytest.mark.asyncio
async def test_teardown_waits_for_prepare_completion_before_worker(
    main_module, tmp_path: Path, monkeypatch
):
    """关闭时若 prepare 未结束：先等 stop_active 落库，再 worker.shutdown。"""
    store = ExecutionStore(tmp_path / "scheduler.sqlite")
    store.init()

    state = AppState(tmp_path)
    order: list[str] = []

    worker = SimpleNamespace(
        tasks=SimpleNamespace(start=MagicMock(return_value=True), stop=MagicMock()),
        device=SimpleNamespace(
            reset_connection_state=MagicMock(),
            build_device_model_from_config=MagicMock(return_value=object()),
            connect=MagicMock(return_value=True),
            set_resource=MagicMock(return_value=True),
        ),
        events=SimpleNamespace(send_log=MagicMock(), send_notification=MagicMock()),
        interface=None,
        shutdown=MagicMock(side_effect=lambda: order.append("worker")),
    )
    state.worker = worker
    state.device.connected = True
    state.device.configuration_locked = True
    state.device.controller_name = "ADB"
    state.device.current_resource_name = "Official"
    state.task.running = False
    state.task.last_status = "success"

    coord = ExecutionCoordinator(state, store)
    state.execution_coordinator = coord

    scheduler = SimpleNamespace(
        shutdown=AsyncMock(side_effect=lambda: order.append("scheduler"))
    )
    state.scheduler_manager = scheduler

    # 挂起 prepare：模拟关闭发生在 setup 阶段
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_prepare(**kwargs):
        del kwargs
        started.set()
        await release.wait()
        return "stopped", "任务已终止"

    monkeypatch.setattr(coord, "_prepare_and_run", slow_prepare)

    # 将 main.app_state 指到本 fixture 状态
    monkeypatch.setattr(main_module, "app_state", state)

    admission = await coord.submit_manual(_manual_payload())
    assert admission.accepted is True
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert state.active_run is not None
    assert store.list()[0].status == "running"

    # log_monitor 替身：被 cancel 后应记入顺序
    async def fake_monitor():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            order.append("monitor")
            raise

    monitor_task = asyncio.create_task(fake_monitor())

    # 稍后释放 prepare，模拟 stop_active 等待期间完成
    async def release_soon():
        await asyncio.sleep(0.05)
        order.append("execution_finishing")
        release.set()

    asyncio.create_task(release_soon())

    await main_module.teardown_runtime(monitor_task)

    # store 已终态、槽位已清
    rows = store.list()
    assert len(rows) == 1
    assert rows[0].status == "stopped"
    assert rows[0].finished_at is not None
    assert state.active_run is None
    assert state.active_execution_task is None

    # 顺序：scheduler → 执行收尾 → worker → monitor
    assert order.index("scheduler") < order.index("execution_finishing")
    assert order.index("execution_finishing") < order.index("worker")
    assert order.index("worker") < order.index("monitor")
    scheduler.shutdown.assert_awaited_once()
    worker.shutdown.assert_called_once()
    worker.tasks.stop.assert_called_once()


@pytest.mark.asyncio
async def test_teardown_no_active_run_still_shuts_down(
    main_module, monkeypatch, tmp_path
):
    """无活跃执行时仍按序关闭，且 finally 释放 ownership。"""
    state = AppState(tmp_path)
    order: list[str] = []
    state.worker = SimpleNamespace(
        shutdown=MagicMock(side_effect=lambda: order.append("worker"))
    )
    state.scheduler_manager = SimpleNamespace(
        shutdown=AsyncMock(side_effect=lambda: order.append("scheduler"))
    )
    state.execution_coordinator = SimpleNamespace(active_run=lambda: None)
    ownership = SimpleNamespace(
        release=MagicMock(side_effect=lambda: order.append("lock"))
    )
    state.runtime_ownership = ownership
    monkeypatch.setattr(main_module, "app_state", state)

    async def fake_monitor():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            order.append("monitor")
            raise

    monitor_task = asyncio.create_task(fake_monitor())
    await asyncio.sleep(0)  # 让 monitor 进入 wait，便于观察 cancel 路径
    await main_module.teardown_runtime(monitor_task)

    assert order == ["scheduler", "worker", "monitor", "lock"]
    assert state.runtime_ownership is None
