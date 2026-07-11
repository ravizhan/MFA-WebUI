import uuid
from enum import Enum

from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Optional, Literal
from datetime import datetime


TaskOptionValue = str | List[str] | Dict[str, str]
TaskOptionsByTask = Dict[str, Dict[str, TaskOptionValue]]


class ScheduledTaskDeviceConfig(BaseModel):
    """定时任务设备配置"""

    controller_name: str = Field(..., description="控制器名称")
    device_type: Literal["Adb", "Win32", "Gamepad", "PlayCover"] = Field(
        ..., description="设备类型"
    )
    device_address: str = Field(..., description="设备地址")


def _generate_pre_task_id() -> str:
    """生成前置命令的唯一标识"""
    return str(uuid.uuid4())


class PreTaskCommand(BaseModel):
    """前置 shell 命令配置"""

    id: str = Field(default_factory=_generate_pre_task_id, description="唯一标识")
    command: str = Field(..., description="要执行的 shell 命令")
    enabled: bool = Field(True, description="是否启用")
    timeout: int = Field(30, description="超时时间（秒），范围 1-3600")

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 1 or v > 3600:
            raise ValueError("timeout must be between 1 and 3600")
        return v


class CronTriggerConfig(BaseModel):
    """Cron 触发器配置"""

    type: Literal["cron"] = "cron"
    cron: str = Field(..., description="Cron 表达式，如 '0 9 * * *'")


class DateTriggerConfig(BaseModel):
    """Date 触发器配置"""

    type: Literal["date"] = "date"
    run_date: datetime = Field(..., description="执行日期时间")


class IntervalTriggerConfig(BaseModel):
    """Interval 触发器配置"""

    type: Literal["interval"] = "interval"
    weeks: Optional[int] = Field(None, ge=0, description="周数")
    days: Optional[int] = Field(None, ge=0, description="天数")
    hours: Optional[int] = Field(None, ge=0, description="小时数")
    minutes: Optional[int] = Field(None, ge=0, description="分钟数")
    seconds: Optional[int] = Field(None, ge=0, description="秒数")
    start_date: Optional[datetime] = Field(None, description="开始时间")
    end_date: Optional[datetime] = Field(None, description="结束时间")


TriggerConfig = CronTriggerConfig | DateTriggerConfig | IntervalTriggerConfig


class TaskExecutionPayload(BaseModel):
    """任务执行载荷"""

    task_list: List[str] = Field(default_factory=list, description="要执行的任务列表")
    task_options: TaskOptionsByTask = Field(
        default_factory=dict, description="任务选项"
    )
    preTasks: List[PreTaskCommand] = Field(
        default_factory=list, description="前置 shell 命令列表"
    )


class ScheduledTask(TaskExecutionPayload):
    """定时任务配置"""

    id: str = Field(..., description="任务唯一标识")
    name: str = Field(..., min_length=1, max_length=100, description="任务名称")
    description: Optional[str] = Field(None, max_length=500, description="任务描述")
    enabled: bool = Field(True, description="是否启用")
    trigger_type: Literal["cron", "date", "interval"] = Field(
        ..., description="触发器类型"
    )
    trigger_config: TriggerConfig = Field(..., description="触发器配置")
    controller_name: Optional[str] = Field(None, description="控制器名称")
    device: Optional[ScheduledTaskDeviceConfig] = Field(None, description="设备配置")
    resource_name: Optional[str] = Field(None, description="资源包名称")
    next_run_time: Optional[datetime] = Field(None, description="下次执行时间")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class ScheduledTaskCreate(TaskExecutionPayload):
    """创建定时任务请求"""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    enabled: bool = True
    trigger_type: Literal["cron", "date", "interval"]
    trigger_config: TriggerConfig
    controller_name: Optional[str] = Field(None, description="控制器名称")
    device: Optional[ScheduledTaskDeviceConfig] = Field(None, description="设备配置")
    resource_name: Optional[str] = Field(None, description="资源包名称")


class ScheduledTaskUpdate(BaseModel):
    """更新定时任务请求"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    enabled: Optional[bool] = None
    trigger_type: Optional[Literal["cron", "date", "interval"]] = None
    trigger_config: Optional[TriggerConfig] = None
    controller_name: Optional[str] = Field(None, description="控制器名称")
    device: Optional[ScheduledTaskDeviceConfig] = Field(None, description="设备配置")
    resource_name: Optional[str] = Field(None, description="资源包名称")
    task_list: Optional[List[str]] = None
    task_options: Optional[TaskOptionsByTask] = None
    preTasks: Optional[List[PreTaskCommand]] = None


class TaskExecution(BaseModel):
    """任务执行记录"""

    id: str = Field(..., description="执行记录唯一标识")
    task_id: str = Field(..., description="关联的定时任务ID")
    task_name: str = Field(..., description="任务名称")
    started_at: datetime = Field(..., description="开始时间")
    finished_at: Optional[datetime] = Field(None, description="结束时间")
    status: Literal["running", "success", "failed", "stopped"] = Field(
        ..., description="执行状态"
    )
    error_message: Optional[str] = Field(None, description="错误信息")


class TaskExecutionCreate(BaseModel):
    """创建执行记录请求"""

    task_id: str
    task_name: str
    status: Literal["running", "success", "failed", "stopped"]
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# 系统级计划任务注册模型
# ---------------------------------------------------------------------------


class SystemTaskScope(str, Enum):
    """系统级任务运行范围

    - USER: 用户级，在用户会话中运行，用户登出后不执行
    - SYSTEM: 系统级，以系统身份运行，用户登出后仍执行（注册需提权）
    """

    USER = "user"
    SYSTEM = "system"


RegistrationState = Literal[
    "pending_register",
    "active",
    "orphaned",
    "pending_cleanup",
    "error",
]

PendingOperation = Literal[
    "register",
    "unregister",
    "migrate",
    "repair",
    "none",
]


class OSTriggerSpec(BaseModel):
    """OS 级触发器规格，由 APScheduler 触发器映射而来"""

    trigger_type: Literal["cron", "date", "interval"]
    cron_expression: Optional[str] = Field(
        None, description="cron 类型：5-field cron 表达式"
    )
    run_date: Optional[datetime] = Field(None, description="date 类型：一次性执行时间")
    interval_minutes: Optional[int] = Field(
        None, description="interval 类型：间隔分钟数（整分钟，禁止静默取整）"
    )


class SystemTaskSpec(BaseModel):
    """注册到 OS 调度器的任务规格"""

    task_id: str
    task_name: str
    exe_path: str = Field(
        ..., description="命令可执行文件（frozen: exe；source: python）"
    )
    cli_args: List[str] = Field(
        ..., description="命令行参数，如 source 下 [main.py, --headless, --task, id]"
    )
    trigger: OSTriggerSpec
    scope: SystemTaskScope
    working_dir: str


class ObservedNativeState(BaseModel):
    """Observed native registration state for one scope/identifier."""

    scope: SystemTaskScope
    identifier: str
    present: bool = False
    verified: bool = False
    details: Optional[str] = None


class SystemTaskRegistration(BaseModel):
    """持久化的系统级任务注册记录（transactional durable state）"""

    task_id: str
    task_name: str
    platform: Literal["windows", "macos", "linux"]
    # Desired state
    desired_scope: SystemTaskScope
    desired_trigger: OSTriggerSpec
    desired_exe_path: str = Field(..., description="期望注册的可执行命令路径")
    desired_cli_args: List[str] = Field(default_factory=list)
    desired_working_dir: str = ""
    # Durable lifecycle
    state: RegistrationState = "pending_register"
    pending_operation: PendingOperation = "none"
    # Observed
    observed: List[ObservedNativeState] = Field(default_factory=list)
    system_task_identifier: str = Field(
        "", description="Primary native identifier for desired scope"
    )
    # Diagnostics
    registered_exe_path: str = Field(
        "", description="最后成功注册的 exe/command 路径（兼容旧字段）"
    )
    last_registered_at: Optional[datetime] = None
    last_error: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    # Migration helper
    migration_from_scope: Optional[SystemTaskScope] = None
    # Compatibility: orphaned flag mirrors state==orphaned
    orphaned: bool = Field(False, description="APScheduler 任务已删除但 OS 注册仍存在")
    # Legacy mirrors
    scope: Optional[SystemTaskScope] = None
    trigger_spec: Optional[OSTriggerSpec] = None

    def model_post_init(self, __context) -> None:
        if self.scope is None:
            object.__setattr__(self, "scope", self.desired_scope)
        if self.trigger_spec is None:
            object.__setattr__(self, "trigger_spec", self.desired_trigger)
        if self.orphaned and self.state == "active":
            object.__setattr__(self, "state", "orphaned")
        if self.state == "orphaned":
            object.__setattr__(self, "orphaned", True)


class CapabilityCell(BaseModel):
    """One platform/scope/trigger capability cell."""

    platform: Literal["windows", "macos", "linux"]
    scope: SystemTaskScope
    trigger_type: Literal["cron", "date", "interval"]
    implemented: bool
    verified: bool
    enabled: bool
    reason: str = ""
    warnings: List[str] = Field(default_factory=list)


class SystemCapabilitiesResponse(BaseModel):
    """Capability matrix for native registration."""

    platform: Literal["windows", "macos", "linux"]
    cells: List[CapabilityCell]
    system_scope_enabled: bool
    warnings: List[str] = Field(default_factory=list)


class SystemTaskStatusResponse(BaseModel):
    """系统级注册状态查询响应（authoritative desired + observed）"""

    task_id: str
    registered: bool
    scope: Optional[SystemTaskScope] = None
    platform: Optional[str] = None
    next_run_time: Optional[datetime] = None
    last_error: Optional[str] = None
    path_valid: bool = Field(..., description="注册路径是否与当前 command 一致")
    # Extended authoritative fields
    state: Optional[RegistrationState] = None
    pending_operation: Optional[PendingOperation] = None
    orphaned: bool = False
    desired_scope: Optional[SystemTaskScope] = None
    observed: List[ObservedNativeState] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    enabled: Optional[bool] = None
    verified: Optional[bool] = None
    reason: Optional[str] = None


class SystemRegisterRequest(BaseModel):
    """系统级注册请求"""

    scope: SystemTaskScope = Field(
        SystemTaskScope.USER, description="运行范围：用户级或系统级"
    )
