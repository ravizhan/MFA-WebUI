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
}

// ---------------------------------------------------------------------------
// 系统级计划任务注册
// ---------------------------------------------------------------------------

export type SystemTaskScope = "user" | "system"

export type SystemTaskPlatform = "windows" | "macos" | "linux"

export type SystemTaskState =
  | "pending_register"
  | "active"
  | "orphaned"
  | "pending_cleanup"
  | "error"

export interface OSTriggerSpec {
  trigger_type: TriggerType
  cron_expression?: string
  run_date?: string
  interval_minutes?: number
}

export interface SystemTaskObservation {
  scope: SystemTaskScope
  identifier: string
  present: boolean
  verified: boolean
  details?: string
}

export interface SystemTaskStatus {
  task_id: string
  registered: boolean
  scope?: SystemTaskScope
  platform?: SystemTaskPlatform
  next_run_time?: string
  last_error?: string
  path_valid: boolean
  // Extended authoritative fields
  state?: SystemTaskState
  pending_operation?: string
  orphaned?: boolean
  desired_scope?: SystemTaskScope
  observed?: SystemTaskObservation[]
  warnings?: string[]
  enabled?: boolean
  verified?: boolean
  reason?: string
}

export interface SystemTaskRegistration {
  task_id: string
  task_name: string
  platform: SystemTaskPlatform
  scope: SystemTaskScope | null
  system_task_identifier: string
  trigger_spec: OSTriggerSpec
  registered_exe_path: string
  last_registered_at: string | null
  orphaned: boolean
  // Extended durable fields
  state: SystemTaskState
  pending_operation?: string
  desired_scope: SystemTaskScope
  desired_trigger?: OSTriggerSpec
  desired_exe_path?: string
  desired_cli_args?: string[]
  desired_working_dir?: string
  observed?: SystemTaskObservation[]
  warnings?: string[]
  last_error?: string
  migration_from_scope?: SystemTaskScope
}

export interface SystemTaskCapabilityCell {
  platform: SystemTaskPlatform
  scope: SystemTaskScope
  trigger_type: TriggerType
  implemented: boolean
  verified: boolean
  enabled: boolean
  reason: string
  warnings: string[]
}

export interface SystemTaskCapabilities {
  platform: string
  cells: SystemTaskCapabilityCell[]
  system_scope_enabled: boolean
  warnings: string[]
}

export interface SystemRegisterRequest {
  scope: SystemTaskScope
}

export interface SystemTaskRepairResult {
  repaired: number
  failed: number
  details: string[]
}
