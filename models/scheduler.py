import uuid

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Dict, Optional, Literal
from datetime import datetime

TaskOptionValue = str | List[str] | Dict[str, str]
TaskOptionsByTask = Dict[str, Dict[str, TaskOptionValue]]

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
    weeks: Optional[int] = Field(None, ge=0, description="周数")
    days: Optional[int] = Field(None, ge=0, description="天数")
    hours: Optional[int] = Field(None, ge=0, description="小时数")
    minutes: Optional[int] = Field(None, ge=0, description="分钟数")
    seconds: Optional[int] = Field(None, ge=0, description="秒数")
    start_date: Optional[datetime] = Field(None, description="开始时间")
    end_date: Optional[datetime] = Field(None, description="结束时间")

    @model_validator(mode="after")
    def _check_min_interval(self) -> "IntervalTriggerConfig":
        total = (
            (self.weeks or 0) * 604800
            + (self.days or 0) * 86400
            + (self.hours or 0) * 3600
            + (self.minutes or 0) * 60
            + (self.seconds or 0)
        )
        if total < 1:
            raise ValueError("间隔总时长不能小于 1 秒")
        return self


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


class ManualStartPayload(TaskExecutionPayload):
    """手动启动载荷（含设备与资源信息）"""

    controller_name: str = Field(..., description="控制器名称")
    device: ScheduledTaskDeviceConfig = Field(..., description="设备配置")
    resource_name: str = Field(..., description="资源包名称")


class StartConflict(BaseModel):
    """手动启动冲突信息"""

    code: Literal["busy_manual", "busy_scheduled", "update_in_progress"] = Field(
        ..., description="冲突代码"
    )
    message: str = Field(..., description="冲突描述")
    active_run_id: str = Field(..., description="当前运行 ID")
    active_task_name: str = Field(..., description="当前运行任务名称")
    active_origin: ExecutionOrigin = Field(..., description="当前运行来源")


class ScheduledTask(TaskExecutionPayload):
    """定时任务配置"""

    id: str = Field(..., description="任务唯一标识")
    name: str = Field(..., min_length=1, max_length=100, description="任务名称")
    description: Optional[str] = Field(None, max_length=500, description="任务描述")
    enabled: bool = Field(True, description="是否启用")
    wakeup_enabled: bool = Field(
        False, description="是否启用系统级唤醒（应用关闭后仍运行）"
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
    wakeup_enabled: bool = False
    trigger_config: TriggerConfig
    controller_name: Optional[str] = Field(None, description="控制器名称")
    device: Optional[ScheduledTaskDeviceConfig] = Field(None, description="设备配置")
    resource_name: Optional[str] = Field(None, description="资源包名称")


class ScheduledTaskUpdate(BaseModel):
    """更新定时任务请求"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    enabled: Optional[bool] = None
    wakeup_enabled: Optional[bool] = None
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
    task_id: Optional[str] = Field(None, description="关联的定时任务ID（手动执行为空）")
    task_name: str = Field(..., description="任务名称")
    origin: ExecutionOrigin = Field("in_app", description="执行来源")
    occurrence_id: Optional[str] = Field(None, description="调度发生次标识")
    scheduled_for: Optional[datetime] = Field(None, description="计划执行时间")
    blocker_task_name: Optional[str] = Field(None, description="冲突的占用任务名称")
    started_at: datetime = Field(..., description="开始时间")
    finished_at: Optional[datetime] = Field(None, description="结束时间")
    status: ExecutionStatus = Field(..., description="执行状态")
    error_message: Optional[str] = Field(None, description="错误信息")


class TaskExecutionCreate(BaseModel):
    """创建执行记录请求"""

    task_id: Optional[str] = None
    task_name: str
    origin: ExecutionOrigin = "in_app"
    status: ExecutionStatus
    error_message: Optional[str] = None
