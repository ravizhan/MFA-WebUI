import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TaskOptionValue = str | list[str] | dict[str, str]
TaskOptionsByTask = dict[str, dict[str, TaskOptionValue]]

ExecutionOrigin = Literal["manual", "in_app", "native"]
ExecutionStatus = Literal[
    "running",
    "success",
    "failed",
    "stopped",
    "skipped_busy_manual",
    "skipped_busy_scheduled",
    "skipped_update_in_progress",
    "missed_deadline",
]


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
    weeks: int | None = Field(None, ge=0, description="周数")
    days: int | None = Field(None, ge=0, description="天数")
    hours: int | None = Field(None, ge=0, description="小时数")
    minutes: int | None = Field(None, ge=0, description="分钟数")
    seconds: int | None = Field(None, ge=0, description="秒数")
    start_date: datetime | None = Field(None, description="开始时间")
    end_date: datetime | None = Field(None, description="结束时间")


TriggerConfig = CronTriggerConfig | DateTriggerConfig | IntervalTriggerConfig


class TaskExecutionPayload(BaseModel):
    """任务执行载荷"""

    task_list: list[str] = Field(default_factory=list, description="要执行的任务列表")
    task_options: TaskOptionsByTask = Field(
        default_factory=dict, description="任务选项"
    )
    preTasks: list[PreTaskCommand] = Field(
        default_factory=list, description="前置 shell 命令列表"
    )


class ScheduledTask(TaskExecutionPayload):
    """定时任务配置"""

    id: str = Field(..., description="任务唯一标识")
    name: str = Field(..., min_length=1, max_length=100, description="任务名称")
    description: str | None = Field(None, max_length=500, description="任务描述")
    enabled: bool = Field(True, description="是否启用")
    trigger_config: TriggerConfig = Field(..., description="触发器配置")
    controller_name: str | None = Field(None, description="控制器名称")
    device: ScheduledTaskDeviceConfig | None = Field(None, description="设备配置")
    resource_name: str | None = Field(None, description="资源包名称")
    # APS-owned native user-level wakeup flag (False = no OS registration)
    wakeup_enabled: bool = Field(
        False, description="是否注册用户级 OS 原生唤醒（False 表示关闭）"
    )
    next_run_time: datetime | None = Field(None, description="下次执行时间")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class ScheduledTaskCreate(TaskExecutionPayload):
    """创建定时任务请求"""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    enabled: bool = True
    trigger_config: TriggerConfig
    controller_name: str | None = Field(None, description="控制器名称")
    device: ScheduledTaskDeviceConfig | None = Field(None, description="设备配置")
    resource_name: str | None = Field(None, description="资源包名称")
    wakeup_enabled: bool = False


class ScheduledTaskUpdate(BaseModel):
    """更新定时任务请求"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    enabled: bool | None = None
    trigger_config: TriggerConfig | None = None
    controller_name: str | None = Field(None, description="控制器名称")
    device: ScheduledTaskDeviceConfig | None = Field(None, description="设备配置")
    resource_name: str | None = Field(None, description="资源包名称")
    task_list: list[str] | None = None
    task_options: TaskOptionsByTask | None = None
    preTasks: list[PreTaskCommand] | None = None
    # omitted=keep; true/false via model_fields_set (explicit false disables wakeup)
    wakeup_enabled: bool | None = None


class TaskExecution(BaseModel):
    """任务执行记录"""

    id: str
    task_id: str | None
    task_name: str
    origin: ExecutionOrigin
    occurrence_id: str | None = None
    scheduled_for: datetime | None = None
    status: ExecutionStatus
    blocker_run_id: str | None = None
    blocker_task_name: str | None = None
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class StartConflict(BaseModel):
    """手动启动冲突信息"""

    code: Literal["busy_manual", "busy_scheduled", "update_in_progress"]
    message: str
    active_run_id: str
    active_task_name: str
    active_origin: ExecutionOrigin


class ManualStartPayload(TaskExecutionPayload):
    """手动启动请求载荷（设备/资源在 admission 之后由后端准备）"""

    controller_name: str
    device: ScheduledTaskDeviceConfig
    resource_name: str
