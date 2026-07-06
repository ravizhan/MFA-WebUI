"""
系统级计划任务编排服务。

职责：
- 平台检测 + 委托后端注册/卸载/查询
- 触发器格式映射（APScheduler → OS 格式）
- 注册状态持久化（config/system_tasks.json）
- 启动时自愈（路径变化 → 重新注册；OS 缺失 → 重新注册；孤儿标记）
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal, cast

import json_utils as json

from models.scheduler import (
    OSTriggerSpec,
    SystemTaskRegistration,
    SystemTaskScope,
    SystemTaskSpec,
    SystemTaskStatusResponse,
    TriggerConfig,
)
from services.system_scheduler_backend import (
    SystemSchedulerBackend,
    get_backend,
    map_trigger_to_os_spec,
)

logger = logging.getLogger(__name__)

_STATE_VERSION = 1

# 平台标识类型
PlatformName = str  # "windows" | "macos" | "linux"


class _SystemTaskState:
    """system_tasks.json 的内存表示"""

    def __init__(self, version: int = _STATE_VERSION):
        self.version = version
        self.registrations: list[SystemTaskRegistration] = []


class SystemTaskService:
    """系统级计划任务编排服务"""

    def __init__(self, app_root_dir: Path):
        self._app_root_dir = app_root_dir
        self._config_dir = app_root_dir / "config"
        self._state_file = self._config_dir / "system_tasks.json"
        self._backend: Optional[SystemSchedulerBackend] = None

    # ------------------------------------------------------------------
    # 后端
    # ------------------------------------------------------------------

    @property
    def backend(self) -> SystemSchedulerBackend:
        """惰性初始化平台后端"""
        if self._backend is None:
            self._backend = get_backend()
        return self._backend

    @property
    def current_exe_path(self) -> str:
        """当前 MWU 可执行文件路径"""
        return sys.executable

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------

    def _load_state(self) -> _SystemTaskState:
        """从 JSON 文件加载注册状态"""
        if not self._state_file.exists():
            return _SystemTaskState()
        try:
            with self._state_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            state = _SystemTaskState(version=data.get("version", _STATE_VERSION))
            for reg_data in data.get("registrations", []):
                state.registrations.append(
                    SystemTaskRegistration.model_validate(reg_data)
                )
            return state
        except Exception as e:
            logger.error(f"加载 system_tasks.json 失败，使用空状态: {e}")
            return _SystemTaskState()

    def _save_state(self, state: _SystemTaskState) -> None:
        """保存注册状态到 JSON 文件"""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "version": state.version,
            "registrations": [
                reg.model_dump(mode="json") for reg in state.registrations
            ],
        }
        with self._state_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def _find_registration(
        self, state: _SystemTaskState, task_id: str
    ) -> Optional[SystemTaskRegistration]:
        """在状态中查找指定任务的注册记录"""
        for reg in state.registrations:
            if reg.task_id == task_id:
                return reg
        return None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def register(
        self,
        task_id: str,
        task_name: str,
        trigger_config: TriggerConfig,
        scope: SystemTaskScope,
    ) -> SystemTaskStatusResponse:
        """注册任务到 OS 调度器（幂等：已存在则更新）

        Args:
            task_id: APScheduler 任务 ID（UUID 格式）
            task_name: 任务名称
            trigger_config: APScheduler 触发器配置
            scope: 运行范围（用户级/系统级）

        Returns:
            注册后的状态响应

        Raises:
            PermissionError: 系统级注册时用户取消了提权
            ValueError: 触发器不支持或 task_id 格式无效
        """
        # 映射触发器
        trigger_spec = map_trigger_to_os_spec(trigger_config)

        # 构造注册规格
        spec = SystemTaskSpec(
            task_id=task_id,
            task_name=task_name,
            exe_path=self.current_exe_path,
            cli_args=["--headless", "--task", task_id],
            trigger=trigger_spec,
            scope=scope,
            working_dir=str(self._app_root_dir),
        )

        # 调用后端注册
        await self.backend.register(spec)

        # 持久化注册记录
        state = self._load_state()
        existing = self._find_registration(state, task_id)
        now = datetime.now()

        if existing:
            existing.task_name = task_name
            existing.scope = scope
            existing.trigger_spec = trigger_spec
            existing.registered_exe_path = self.current_exe_path
            existing.last_registered_at = now
            existing.orphaned = False
        else:
            state.registrations.append(
                SystemTaskRegistration(
                    task_id=task_id,
                    task_name=task_name,
                    platform=cast(
                        Literal["windows", "macos", "linux"],
                        self.backend.platform_name,
                    ),
                    scope=scope,
                    system_task_identifier=self._build_identifier(task_id, scope),
                    trigger_spec=trigger_spec,
                    registered_exe_path=self.current_exe_path,
                    last_registered_at=now,
                    orphaned=False,
                )
            )
        self._save_state(state)

        # 查询下次运行时间
        next_run = await self.backend.get_next_run_time(task_id, scope)

        return SystemTaskStatusResponse(
            task_id=task_id,
            registered=True,
            scope=scope,
            platform=cast(
                Literal["windows", "macos", "linux"],
                self.backend.platform_name,
            ),
            next_run_time=next_run,
            path_valid=True,
        )

    async def unregister(self, task_id: str) -> SystemTaskStatusResponse:
        """从 OS 调度器卸载任务（幂等：不存在则静默成功）

        Args:
            task_id: APScheduler 任务 ID

        Returns:
            卸载后的状态响应
        """
        state = self._load_state()
        reg = self._find_registration(state, task_id)

        if reg:
            try:
                await self.backend.unregister(task_id, reg.scope)
            except Exception as e:
                logger.warning(f"卸载系统任务 {task_id} 时后端出错: {e}")
            state.registrations.remove(reg)
            self._save_state(state)

        return SystemTaskStatusResponse(
            task_id=task_id,
            registered=False,
            path_valid=True,
        )

    async def get_status(self, task_id: str) -> SystemTaskStatusResponse:
        """查询任务的系统级注册状态"""
        state = self._load_state()
        reg = self._find_registration(state, task_id)

        if not reg:
            return SystemTaskStatusResponse(
                task_id=task_id,
                registered=False,
                path_valid=True,
            )

        # 检查 OS 中是否仍注册
        try:
            os_registered = await self.backend.is_registered(task_id, reg.scope)
        except Exception as e:
            logger.warning(f"查询系统任务 {task_id} 状态时出错: {e}")
            os_registered = False

        next_run = None
        if os_registered:
            try:
                next_run = await self.backend.get_next_run_time(task_id, reg.scope)
            except Exception:
                pass

        path_valid = reg.registered_exe_path == self.current_exe_path

        return SystemTaskStatusResponse(
            task_id=task_id,
            registered=os_registered,
            scope=reg.scope,
            platform=reg.platform,
            next_run_time=next_run,
            last_error=None if os_registered else "任务在 OS 中未找到",
            path_valid=path_valid,
        )

    async def list_registered(self) -> list[SystemTaskRegistration]:
        """列出所有系统级注册的任务"""
        state = self._load_state()
        return state.registrations

    async def repair_all(self) -> dict:
        """修复所有失效注册（MWU 启动时调用）

        修复逻辑：
        1. 路径不一致 → 用新路径重新注册
        2. OS 中缺失 → 重新注册
        3. 不自动卸载孤儿任务（APScheduler 已删除但 OS 注册仍在）→ 标记 orphaned

        Returns:
            {"repaired": N, "failed": M, "details": [...]}
        """
        state = self._load_state()
        current_exe = self.current_exe_path
        repaired = 0
        failed = 0
        details: list[str] = []

        for reg in state.registrations:
            try:
                # 检查 OS 中是否仍注册
                os_registered = await self.backend.is_registered(reg.task_id, reg.scope)

                need_repair = False
                reason = ""

                if not os_registered:
                    need_repair = True
                    reason = "OS 中未找到"
                elif reg.registered_exe_path != current_exe:
                    need_repair = True
                    reason = f"路径变化: {reg.registered_exe_path} → {current_exe}"

                if need_repair:
                    # 重新注册
                    spec = SystemTaskSpec(
                        task_id=reg.task_id,
                        task_name=reg.task_name,
                        exe_path=current_exe,
                        cli_args=["--headless", "--task", reg.task_id],
                        trigger=reg.trigger_spec,
                        scope=reg.scope,
                        working_dir=str(self._app_root_dir),
                    )
                    await self.backend.register(spec)
                    reg.registered_exe_path = current_exe
                    reg.last_registered_at = datetime.now()
                    reg.orphaned = False
                    repaired += 1
                    details.append(f"修复 {reg.task_id}: {reason}")
                else:
                    # 检查是否为孤儿（APScheduler 任务可能已删除，但这里无法直接判断）
                    # 孤儿标记由调用方（API 层）在删除任务时设置
                    pass

            except Exception as e:
                failed += 1
                details.append(f"修复 {reg.task_id} 失败: {e}")
                logger.error(f"修复系统任务 {reg.task_id} 失败: {e}")

        self._save_state(state)

        result = {"repaired": repaired, "failed": failed, "details": details}
        logger.info(f"系统任务修复完成: 修复 {repaired} 个, 失败 {failed} 个")
        return result

    async def mark_orphaned(self, task_id: str) -> None:
        """标记任务为孤儿（APScheduler 任务已删除但 OS 注册仍存在）

        不自动卸载，仅标记，由前端提示用户手动处理。
        """
        state = self._load_state()
        reg = self._find_registration(state, task_id)
        if reg:
            reg.orphaned = True
            self._save_state(state)
            logger.info(f"系统任务 {task_id} 已标记为孤儿")

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _build_identifier(self, task_id: str, scope: SystemTaskScope) -> str:
        """构建系统任务标识符（用于记录，实际标识由后端管理）"""
        platform_name = self.backend.platform_name
        if platform_name == "windows":
            return f"\\MWU\\{task_id}"
        elif platform_name == "macos":
            prefix = (
                "com.mwu.daemon" if scope == SystemTaskScope.SYSTEM else "com.mwu.task"
            )
            return f"{prefix}.{task_id}"
        else:  # linux
            return f"mwu-{task_id}"
