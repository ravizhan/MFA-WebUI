import type { TaskOptionValue } from "@/types/scheduler/model"

export const CUSTOM_PRESET_NAME = "__mwu_reserved_custom_preset__"

export interface TaskListItem {
  id: string
  name: string
  order: number
  checked?: boolean
}

export interface TaskPresetSnapshot {
  taskOrder: string[]
  taskChecked: Record<string, boolean>
  taskOptions: Record<string, TaskOptionValue>
}

export interface PersistedTaskConfig {
  selectedPreset: string
  presets: Record<string, TaskPresetSnapshot>
}
