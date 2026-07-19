import type { PreTaskCommand } from "@/types/taskConfigModel"

export type { PreTaskCommand }

export type TriggerType = "cron" | "date" | "interval"

export type ExecutionOrigin = "manual" | "in_app" | "native"

export type ExecutionStatus =
  | "running"
  | "success"
  | "failed"
  | "stopped"
  | "skipped_busy_manual"
  | "skipped_busy_scheduled"
  | "skipped_update_in_progress"
  | "missed_deadline"

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
  task_id: string | null
  task_name: string
  origin: ExecutionOrigin
  occurrence_id: string | null
  scheduled_for: string | null
  status: ExecutionStatus
  blocker_run_id: string | null
  blocker_task_name: string | null
  error_message: string | null
  started_at: string
  finished_at: string | null
}

export interface StartConflict {
  code: "busy_manual" | "busy_scheduled" | "update_in_progress"
  message: string
  active_run_id: string
  active_task_name: string
  active_origin: ExecutionOrigin
}

export type ManualStartResult =
  | { accepted: true; runId: string }
  | { accepted: false; conflict?: StartConflict; error?: string }

export interface ManualStartPayload extends TaskExecutionPayload {
  controller_name: string
  device: ScheduledTaskDeviceConfig
  resource_name: string
}

export interface SchedulerApiResponse {
  status: "success" | "failed"
  message?: string
  tasks?: ScheduledTask[]
  task?: ScheduledTask
  executions?: TaskExecution[]
}
