from __future__ import annotations

import uuid

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TaskOptionValue = str | list[str] | dict[str, str]
TaskOptionsByTask = dict[str, dict[str, TaskOptionValue]]


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
    trigger_type: Literal["cron", "date", "interval"] = Field(
        ..., description="触发器类型"
    )
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
    trigger_type: Literal["cron", "date", "interval"]
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
    trigger_type: (Literal["cron", "date", "interval"]) | None = None
    trigger_config: TriggerConfig | None = None
    controller_name: str | None = Field(None, description="控制器名称")
    device: ScheduledTaskDeviceConfig | None = Field(None, description="设备配置")
    resource_name: str | None = Field(None, description="资源包名称")
    task_list: (list[str]) | None = None
    task_options: TaskOptionsByTask | None = None
    preTasks: (list[PreTaskCommand]) | None = None
    # omitted=keep; true/false via model_fields_set (explicit false disables wakeup)
    wakeup_enabled: bool | None = None


class TaskExecution(BaseModel):
    """任务执行记录"""

    id: str = Field(..., description="执行记录唯一标识")
    task_id: str = Field(..., description="关联的定时任务ID")
    task_name: str = Field(..., description="任务名称")
    started_at: datetime = Field(..., description="开始时间")
    finished_at: datetime | None = Field(None, description="结束时间")
    status: Literal["running", "success", "failed", "stopped"] = Field(
        ..., description="执行状态"
    )
    error_message: str | None = Field(None, description="错误信息")


class TaskExecutionCreate(BaseModel):
    """创建执行记录请求"""

    task_id: str
    task_name: str
    status: Literal["running", "success", "failed", "stopped"]
    error_message: str | None = None


# ---------------------------------------------------------------------------
# 用户级原生唤醒注册模型
# ---------------------------------------------------------------------------


OperationalState = Literal["active", "error"]

# Exact allowlist of keys written to system_tasks.json.
OPERATIONAL_STATE_KEYS = frozenset(
    {
        "task_id",
        "platform",
        "state",
        "registered_exe_path",
        "last_registered_at",
        "last_error",
    }
)

OPERATIONAL_STATE_VERSION = 4


class OSTriggerSpec(BaseModel):
    """OS 级触发器规格，由 APScheduler 触发器映射而来"""

    trigger_type: Literal["cron", "date", "interval"]
    cron_expression: str | None = Field(
        None, description="cron 类型：5-field cron 表达式"
    )
    run_date: datetime | None = Field(None, description="date 类型：一次性执行时间")
    interval_minutes: int | None = Field(
        None, description="interval 类型：间隔分钟数（整分钟，禁止静默取整）"
    )


class SystemTaskSpec(BaseModel):
    """注册到 OS 用户级调度器的任务规格"""

    task_id: str
    task_name: str
    exe_path: str = Field(
        ..., description="命令可执行文件（frozen: exe；source: python）"
    )
    cli_args: list[str] = Field(
        ..., description="命令行参数，如 source 下 [main.py, --headless, --task, id]"
    )
    trigger: OSTriggerSpec
    working_dir: str


class SystemTaskOperationalRecord(BaseModel):
    """Persisted operational native-registration record (disk allowlist only)."""

    task_id: str
    platform: Literal["windows", "macos", "linux"]
    state: OperationalState = "active"
    registered_exe_path: str = Field(
        "", description="Last-known registered exe path (diagnostic)"
    )
    last_registered_at: datetime | None = None
    last_error: str | None = None

    def to_operational_dict(self) -> dict:
        """Serialize only operational allowlisted keys."""
        raw = self.model_dump(mode="json")
        return {k: raw[k] for k in OPERATIONAL_STATE_KEYS if k in raw}


class SystemTaskRegistration(BaseModel):
    """API/list DTO for native wakeup registration (hydrated from APS + disk)."""

    task_id: str
    task_name: str = ""
    platform: Literal["windows", "macos", "linux"]
    state: OperationalState = "active"
    registered_exe_path: str = ""
    last_registered_at: datetime | None = None
    last_error: str | None = None
    trigger_spec: OSTriggerSpec | None = None
    next_run_time: datetime | None = None
    registered: bool = False
    verified: bool = False
    path_valid: bool = False
    reason: str | None = None
    enabled: bool | None = None


class SystemTaskStatusResponse(BaseModel):
    """原生唤醒注册状态（authoritative APS + native observation）。"""

    task_id: str
    registered: bool
    platform: str | None = None
    task_name: str = ""
    next_run_time: datetime | None = None
    last_error: str | None = None
    path_valid: bool = Field(..., description="注册路径是否与当前 command 一致")
    state: OperationalState | None = None
    registered_exe_path: str = ""
    enabled: bool | None = None
    verified: bool | None = None
    reason: str | None = None


class TaskUpdateSyncedResult(BaseModel):
    """APS update + native reconcile partial-success result.

    APS success with native failure still carries ``task`` and surfaces
    ``native_error`` / ``native_status`` without treating the request as failed.
    """

    task: ScheduledTask | None = None
    aps_outcome: Literal["success", "not_found", "error"] = "success"
    aps_error: str | None = None
    native_status: SystemTaskStatusResponse | None = None
    native_error: str | None = None


class ReconcileTaskResult(BaseModel):
    """Single-task reconcile outcome for repair/reconcile_all aggregation."""

    task_id: str
    action: Literal[
        "noop",
        "registered",
        "updated",
        "cleaned",
        "materialized",
        "error",
        "skipped",
    ] = "noop"
    detail: str = ""
    native_error: str | None = None
