"""SystemTaskService 单元测试。

测试覆盖：
- 状态持久化（加载/保存）
- 注册/卸载流程（mock 后端）
- 自愈逻辑（路径变化、OS 缺失、孤儿标记）
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scheduler import (
    CronTriggerConfig,
    OSTriggerSpec,
    SystemTaskRegistration,
    SystemTaskScope,
    SystemTaskSpec,
)
from services.system_scheduler import SystemTaskService, _SystemTaskState


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """临时配置目录"""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return tmp_path


@pytest.fixture
def service(temp_config_dir: Path) -> SystemTaskService:
    """SystemTaskService 实例（使用临时目录）"""
    return SystemTaskService(temp_config_dir)


@pytest.fixture
def mock_backend():
    """Mock 后端"""
    backend = MagicMock()
    backend.platform_name = "linux"
    backend.register = AsyncMock()
    backend.unregister = AsyncMock()
    backend.is_registered = AsyncMock(return_value=True)
    backend.get_next_run_time = AsyncMock(return_value=None)
    backend.list_registered = AsyncMock(return_value=[])
    return backend


# ---------------------------------------------------------------------------
# 状态持久化
# ---------------------------------------------------------------------------


class TestStatePersistence:
    """状态持久化测试"""

    def test_load_empty_state(self, service: SystemTaskService):
        """无文件时返回空状态"""
        state = service._load_state()
        assert state.version == 1
        assert len(state.registrations) == 0

    def test_save_and_load(self, service: SystemTaskService):
        """保存后能正确加载"""
        state = _SystemTaskState()
        state.registrations.append(
            SystemTaskRegistration(
                task_id="abc-123",
                task_name="测试任务",
                platform="linux",
                scope=SystemTaskScope.USER,
                system_task_identifier="mwu-abc-123",
                trigger_spec=OSTriggerSpec(
                    trigger_type="cron", cron_expression="0 9 * * *"
                ),
                registered_exe_path="/usr/bin/mwu",
                last_registered_at=datetime(2026, 7, 6, 12, 0, 0),
                orphaned=False,
            )
        )
        service._save_state(state)

        loaded = service._load_state()
        assert len(loaded.registrations) == 1
        reg = loaded.registrations[0]
        assert reg.task_id == "abc-123"
        assert reg.task_name == "测试任务"
        assert reg.scope == SystemTaskScope.USER
        assert reg.trigger_spec.cron_expression == "0 9 * * *"

    def test_load_corrupted_file(self, service: SystemTaskService):
        """损坏的 JSON 文件返回空状态"""
        service._state_file.write_text("{ invalid json", encoding="utf-8")
        state = service._load_state()
        assert len(state.registrations) == 0

    def test_find_registration(self, service: SystemTaskService):
        """查找注册记录"""
        state = _SystemTaskState()
        reg = SystemTaskRegistration(
            task_id="test-id",
            task_name="Test",
            platform="linux",
            scope=SystemTaskScope.USER,
            system_task_identifier="mwu-test-id",
            trigger_spec=OSTriggerSpec(
                trigger_type="cron", cron_expression="* * * * *"
            ),
            registered_exe_path="/path/to/exe",
            last_registered_at=datetime.now(),
            orphaned=False,
        )
        state.registrations.append(reg)

        found = service._find_registration(state, "test-id")
        assert found is not None
        assert found.task_id == "test-id"

        not_found = service._find_registration(state, "nonexistent")
        assert not_found is None


# ---------------------------------------------------------------------------
# 注册/卸载流程
# ---------------------------------------------------------------------------


class TestRegisterUnregister:
    """注册/卸载流程测试"""

    @pytest.mark.asyncio
    async def test_register_new_task(self, service: SystemTaskService, mock_backend):
        """注册新任务"""
        service._backend = mock_backend

        status = await service.register(
            task_id="abc-123",
            task_name="测试任务",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        assert status.registered is True
        assert status.scope == SystemTaskScope.USER
        assert status.platform == "linux"
        mock_backend.register.assert_called_once()

        # 验证状态已持久化
        state = service._load_state()
        assert len(state.registrations) == 1
        assert state.registrations[0].task_id == "abc-123"

    @pytest.mark.asyncio
    async def test_register_updates_existing(
        self, service: SystemTaskService, mock_backend
    ):
        """重复注册更新已有记录"""
        service._backend = mock_backend

        # 第一次注册
        await service.register(
            task_id="abc-123",
            task_name="任务1",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        # 第二次注册（更新）
        await service.register(
            task_id="abc-123",
            task_name="任务2",
            trigger_config=CronTriggerConfig(cron="0 10 * * *"),
            scope=SystemTaskScope.SYSTEM,
        )

        state = service._load_state()
        assert len(state.registrations) == 1
        reg = state.registrations[0]
        assert reg.task_name == "任务2"
        assert reg.scope == SystemTaskScope.SYSTEM
        assert reg.trigger_spec.cron_expression == "0 10 * * *"

    @pytest.mark.asyncio
    async def test_unregister_existing(self, service: SystemTaskService, mock_backend):
        """卸载已注册的任务"""
        service._backend = mock_backend

        # 先注册
        await service.register(
            task_id="abc-123",
            task_name="测试",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        # 卸载
        status = await service.unregister("abc-123")
        assert status.registered is False
        mock_backend.unregister.assert_called_once()

        # 验证状态已清除
        state = service._load_state()
        assert len(state.registrations) == 0

    @pytest.mark.asyncio
    async def test_unregister_nonexistent(
        self, service: SystemTaskService, mock_backend
    ):
        """卸载不存在的任务（幂等）"""
        service._backend = mock_backend
        status = await service.unregister("nonexistent-id")
        assert status.registered is False
        mock_backend.unregister.assert_not_called()


# ---------------------------------------------------------------------------
# 自愈逻辑
# ---------------------------------------------------------------------------


class TestRepairAll:
    """自愈逻辑测试"""

    @pytest.mark.asyncio
    async def test_repair_path_change(self, service: SystemTaskService, mock_backend):
        """路径变化时重新注册"""
        service._backend = mock_backend

        # 注册任务（使用旧路径）
        with patch.object(SystemTaskService, "current_exe_path", "/old/path/exe"):
            await service.register(
                task_id="abc-123",
                task_name="测试",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )

        # 模拟路径变化
        with patch.object(SystemTaskService, "current_exe_path", "/new/path/exe"):
            mock_backend.is_registered.return_value = True
            result = await service.repair_all()

        assert result["repaired"] == 1
        assert result["failed"] == 0
        # 后端应被调用重新注册
        assert mock_backend.register.call_count >= 2  # 初始注册 + 修复注册

        # 验证路径已更新
        state = service._load_state()
        assert state.registrations[0].registered_exe_path == "/new/path/exe"

    @pytest.mark.asyncio
    async def test_repair_os_missing(self, service: SystemTaskService, mock_backend):
        """OS 中缺失时重新注册"""
        service._backend = mock_backend

        # 注册任务
        await service.register(
            task_id="abc-123",
            task_name="测试",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        # 模拟 OS 中已删除
        mock_backend.is_registered.return_value = False
        result = await service.repair_all()

        assert result["repaired"] == 1
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_repair_nothing_needed(
        self, service: SystemTaskService, mock_backend
    ):
        """无需修复时正常返回"""
        service._backend = mock_backend

        await service.register(
            task_id="abc-123",
            task_name="测试",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        # 路径一致，OS 中已注册
        mock_backend.is_registered.return_value = True
        result = await service.repair_all()

        assert result["repaired"] == 0
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_repair_backend_failure(
        self, service: SystemTaskService, mock_backend
    ):
        """后端修复失败时记录失败"""
        service._backend = mock_backend

        await service.register(
            task_id="abc-123",
            task_name="测试",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        # 模拟 OS 中缺失 + 重新注册失败
        mock_backend.is_registered.return_value = False
        mock_backend.register.side_effect = Exception("后端错误")
        result = await service.repair_all()

        assert result["repaired"] == 0
        assert result["failed"] == 1
        assert len(result["details"]) == 1


# ---------------------------------------------------------------------------
# 孤儿标记
# ---------------------------------------------------------------------------


class TestMarkOrphaned:
    """孤儿标记测试"""

    @pytest.mark.asyncio
    async def test_mark_orphaned(self, service: SystemTaskService, mock_backend):
        """标记孤儿任务"""
        service._backend = mock_backend

        await service.register(
            task_id="abc-123",
            task_name="测试",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        await service.mark_orphaned("abc-123")

        state = service._load_state()
        assert state.registrations[0].orphaned is True

    @pytest.mark.asyncio
    async def test_mark_orphaned_nonexistent(
        self, service: SystemTaskService, mock_backend
    ):
        """标记不存在的任务（静默成功）"""
        service._backend = mock_backend
        await service.mark_orphaned("nonexistent")
        # 不应抛出异常
        state = service._load_state()
        assert len(state.registrations) == 0


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------


class TestGetStatus:
    """状态查询测试"""

    @pytest.mark.asyncio
    async def test_get_status_registered(
        self, service: SystemTaskService, mock_backend
    ):
        """查询已注册任务状态"""
        service._backend = mock_backend

        await service.register(
            task_id="abc-123",
            task_name="测试",
            trigger_config=CronTriggerConfig(cron="0 9 * * *"),
            scope=SystemTaskScope.USER,
        )

        mock_backend.is_registered.return_value = True
        status = await service.get_status("abc-123")

        assert status.registered is True
        assert status.scope == SystemTaskScope.USER
        assert status.path_valid is True

    @pytest.mark.asyncio
    async def test_get_status_not_registered(
        self, service: SystemTaskService, mock_backend
    ):
        """查询未注册任务状态"""
        service._backend = mock_backend
        status = await service.get_status("nonexistent")

        assert status.registered is False
        assert status.path_valid is True

    @pytest.mark.asyncio
    async def test_get_status_path_invalid(
        self, service: SystemTaskService, mock_backend
    ):
        """路径不一致时 path_valid 为 False"""
        service._backend = mock_backend

        # 使用旧路径注册
        with patch.object(SystemTaskService, "current_exe_path", "/old/path/exe"):
            await service.register(
                task_id="abc-123",
                task_name="测试",
                trigger_config=CronTriggerConfig(cron="0 9 * * *"),
                scope=SystemTaskScope.USER,
            )

        # 路径已变化
        with patch.object(SystemTaskService, "current_exe_path", "/new/path/exe"):
            mock_backend.is_registered.return_value = True
            status = await service.get_status("abc-123")

        assert status.registered is True
        assert status.path_valid is False
