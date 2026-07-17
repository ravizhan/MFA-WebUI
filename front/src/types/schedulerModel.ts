import type { PreTaskCommand } from "@/types/taskConfigModel"

export type TriggerType = "cron" | "date" | "interval"

export type ExecutionStatus = "running" | "success" | "failed" | "stopped"

export interface CronTriggerConfig {
  type: "cron"
  cron: string
}

export interface DateTriggerConfig {
  type: "date"
  run_date: string // ISO 8601 datetime string
}

export interface IntervalTriggerConfig {
  type: "interval"
  weeks?: number
  days?: number
  hours?: number
  minutes?: number
  seconds?: number
  start_date?: string // ISO 8601 datetime string
  end_date?: string // ISO 8601 datetime string
}

export type TriggerConfig = CronTriggerConfig | DateTriggerConfig | IntervalTriggerConfig

export type TaskOptionValue = string | string[] | Record<string, string>
export type NullableTaskOptionValue = TaskOptionValue | null
export type TaskOptionsByTask = Record<string, Record<string, TaskOptionValue>>

export interface TaskExecutionPayload {
  task_list: string[]
  task_options: TaskOptionsByTask
  preTasks: PreTaskCommand[]
}

export interface ScheduledTaskDeviceConfig {
  controller_name: string
  device_type: "Adb" | "Win32" | "Gamepad" | "PlayCover"
  device_address: string
}

export interface ScheduledTask extends TaskExecutionPayload {
  id: string
  name: string
  description?: string
  enabled: boolean
  trigger_type: TriggerType
  trigger_config: TriggerConfig
  controller_name?: string | null
  device?: ScheduledTaskDeviceConfig | null
  resource_name?: string | null
  /** User-level OS wakeup registration */
  wakeup_enabled: boolean
  next_run_time?: string // ISO 8601 datetime string
  created_at: string // ISO 8601 datetime string
  updated_at: string // ISO 8601 datetime string
}

export interface ScheduledTaskCreate extends TaskExecutionPayload {
  name: string
  description?: string
  enabled: boolean
  trigger_type: TriggerType
  trigger_config: TriggerConfig
  controller_name?: string | null
  device?: ScheduledTaskDeviceConfig | null
  resource_name?: string | null
  wakeup_enabled: boolean
}

export interface ScheduledTaskUpdate {
  name?: string
  description?: string
  enabled?: boolean
  trigger_type?: TriggerType
  trigger_config?: TriggerConfig
  controller_name?: string | null
  device?: ScheduledTaskDeviceConfig | null
  resource_name?: string | null
  task_list?: string[]
  task_options?: TaskOptionsByTask
  preTasks?: PreTaskCommand[]
  /** Always send true/false on update when changing wakeup */
  wakeup_enabled?: boolean
}

export interface TaskExecution {
  id: string
  task_id: string
  task_name: string
  started_at: string // ISO 8601 datetime string
  finished_at?: string // ISO 8601 datetime string
  status: ExecutionStatus
  error_message?: string
}

export interface SchedulerApiResponse {
  status: "success" | "failed"
  message?: string
  tasks?: ScheduledTask[]
  task?: ScheduledTask
  executions?: TaskExecution[]
  native_status?: SystemTaskStatus
  native_error?: string
}

// ---------------------------------------------------------------------------
// 系统级计划任务注册（精简 DTO，无 scope/legacy）
// ---------------------------------------------------------------------------

export type SystemTaskPlatform = "windows" | "macos" | "linux"

export type SystemTaskState = "active" | "error"

export interface OSTriggerSpec {
  trigger_type: TriggerType
  cron_expression?: string
  run_date?: string
  interval_minutes?: number
}

/** Authoritative native wakeup status (status endpoint / native_status). */
export interface SystemTaskStatus {
  task_id: string
  task_name?: string
  platform?: SystemTaskPlatform
  state?: SystemTaskState
  registered?: boolean
  enabled?: boolean
  verified?: boolean
  path_valid?: boolean
  registered_exe_path?: string
  next_run_time?: string
  last_error?: string
  reason?: string
  trigger?: OSTriggerSpec
}

/** List DTO for /api/scheduler/system-tasks registrations. */
export interface SystemTaskRegistration {
  task_id: string
  task_name?: string
  platform: SystemTaskPlatform
  state: SystemTaskState
  registered?: boolean
  enabled?: boolean
  verified?: boolean
  path_valid?: boolean
  registered_exe_path?: string
  next_run_time?: string
  last_error?: string
  reason?: string
  trigger?: OSTriggerSpec
}

export interface SystemTaskRepairResult {
  repaired: number
  failed: number
  details: string[]
}
