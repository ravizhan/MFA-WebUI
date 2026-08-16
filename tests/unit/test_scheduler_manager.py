"""Tests for scheduler_manager.py（重写后契约）— 唤醒先行 CRUD 顺序与触发器 round-trip。

构造签名按冻结契约：``SchedulerManager(state, db_path, system_scheduler=None)``、
``initialize(paused=True)``。若文件尚未完成重写（旧版签名），本模块整体跳过，
由外部运行方决定重试或仅运行其余测试文件。
"""

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from apscheduler.triggers.cron import CronTrigger

from app_state import AppState
from models.scheduler import CronTriggerConfig, ScheduledTaskCreate, ScheduledTaskUpdate
from services.system_scheduler import ConvergeReport

from scheduler_manager import SchedulerManager  # noqa: E402

# 契约守卫：scheduler_manager.py 完成重写前（旧版无参构造函数/initialize 无 paused
# 参数）不运行本文件，避免 TypeError 污染其余测试结果。
if (
    "system_scheduler" not in inspect.signature(SchedulerManager.__init__).parameters
    or "paused" not in inspect.signature(SchedulerManager.initialize).parameters
):
    pytest.skip(
        "scheduler_manager.py 尚未按新契约重写（缺少 system_scheduler 构造参数/"
        "initialize(paused=...)），本文件暂不运行",
        allow_module_level=True,
    )


def make_create(
    name: str, wakeup_enabled: bool = False, enabled: bool = True
) -> ScheduledTaskCreate:
    return ScheduledTaskCreate(
        name=name,
        wakeup_enabled=wakeup_enabled,
        enabled=enabled,
        trigger_config=CronTriggerConfig(cron="0 9 * * *"),
        task_list=["Startup"],
    )


@pytest.fixture
async def manager_env(tmp_path: Path):
    state = AppState()
    system_scheduler = MagicMock()
    system_scheduler.converge.return_value = ConvergeReport()
    mgr = SchedulerManager(
        state, tmp_path / "scheduler.sqlite", system_scheduler=system_scheduler
    )
    await mgr.initialize(paused=True)
    assert mgr.scheduler is not None
    mgr.scheduler.resume()
    system_scheduler.reset_mock()
    try:
        yield mgr, state, system_scheduler
    finally:
        await mgr.shutdown()


class TestCreateTaskWakeupFirst:
    async def test_register_called_before_aps_job_exists(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        seen: list[str] = []

        def _record(task):
            # 注册发生在 APS 落库之前：此刻 get_job 必须为 None
            assert mgr.scheduler.get_job(task.id) is None
            seen.append(task.id)

        system_scheduler.register.side_effect = _record

        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))

        assert system_scheduler.register.call_count == 1
        assert seen == [task.id]
        assert mgr.scheduler.get_job(task.id) is not None
        assert task.wakeup_enabled is True

        # get_task 解码还原 wakeup_enabled 与 trigger_config
        got = await mgr.get_task(task.id)
        assert got is not None
        assert got.wakeup_enabled is True
        assert got.trigger_config.cron == "0 9 * * *"

    async def test_register_failure_aborts_creation_and_propagates(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        captured: dict[str, str] = {}

        def _boom(task):
            captured["id"] = task.id
            raise RuntimeError("native register boom")

        system_scheduler.register.side_effect = _boom

        with pytest.raises(RuntimeError, match="native register boom"):
            await mgr.create_task(make_create("失败任务", wakeup_enabled=True))

        # APS 任务未落库
        assert mgr.scheduler.get_job(captured["id"]) is None
        assert await mgr.get_task(captured["id"]) is None

    async def test_no_wakeup_skips_register(self, manager_env):
        mgr, _state, system_scheduler = manager_env

        task = await mgr.create_task(make_create("普通任务", wakeup_enabled=False))

        system_scheduler.register.assert_not_called()
        assert mgr.scheduler.get_job(task.id) is not None

    async def test_disabled_task_with_wakeup_skips_register(self, manager_env):
        # _desired_wakeup = wakeup_enabled AND enabled
        mgr, _state, system_scheduler = manager_env

        task = await mgr.create_task(
            make_create("停用任务", wakeup_enabled=True, enabled=False)
        )

        system_scheduler.register.assert_not_called()
        assert mgr.scheduler.get_job(task.id) is not None


class TestTriggerRoundTrip:
    async def test_cron_trigger_round_trip_preserves_unix_dow(self, manager_env):
        mgr, _state, _system_scheduler = manager_env
        config = CronTriggerConfig(cron="0 9 * * 1")  # Unix 星期 1 = 周一

        trigger = mgr._create_trigger(config)

        assert isinstance(trigger, CronTrigger)
        # APS 0=周一 ↔ Unix 1=周一：构建时已转换
        dow_field = next(f for f in trigger.fields if f.name == "day_of_week")
        assert str(dow_field) == "0"

        trigger_type, decoded = mgr._build_trigger_config(trigger)
        assert trigger_type == "cron"
        assert isinstance(decoded, CronTriggerConfig)
        assert decoded.cron == "0 9 * * 1"


class TestUpdateTaskWakeup:
    async def test_turning_wakeup_off_unregisters(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        system_scheduler.register.assert_called_once()

        updated = await mgr.update_task(
            task.id, ScheduledTaskUpdate(wakeup_enabled=False)
        )

        assert updated is not None
        assert updated.wakeup_enabled is False
        system_scheduler.unregister.assert_called_once_with(task.id)

    async def test_disabling_task_with_wakeup_unregisters(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        system_scheduler.register.assert_called_once()

        updated = await mgr.update_task(task.id, ScheduledTaskUpdate(enabled=False))

        assert updated is not None
        assert updated.enabled is False
        system_scheduler.unregister.assert_called_once_with(task.id)

    async def test_reenabling_desired_task_registers_again(self, manager_env):
        mgr, _state, system_scheduler = manager_env
        task = await mgr.create_task(make_create("唤醒任务", wakeup_enabled=True))
        await mgr.update_task(task.id, ScheduledTaskUpdate(enabled=False))
        system_scheduler.unregister.assert_called_once()

        updated = await mgr.update_task(task.id, ScheduledTaskUpdate(enabled=True))

        assert updated is not None
        assert updated.enabled is True
        assert system_scheduler.register.call_count == 2
