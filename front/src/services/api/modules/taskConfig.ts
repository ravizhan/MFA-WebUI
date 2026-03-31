import type { TaskOptionValue } from "@/types/scheduler/model"
import type { ApiResponse } from "@/services/api/core/types"

export interface TaskConfig {
  taskOrder?: string[]
  taskChecked?: Record<string, boolean>
  taskOptions?: Record<string, TaskOptionValue>
  selectedPreset?: string | null
  presetDirty?: boolean
}

interface TaskConfigResponse {
  status: string
  config: TaskConfig
  message?: string
}

export function getTaskConfig(): Promise<TaskConfig> {
  return fetch("/api/task-config", { method: "GET" })
    .then((res) => res.json())
    .then((data: TaskConfigResponse) => {
      if (data.status === "success") {
        return data.config || {}
      }
      console.error("Failed to load task config:", data.message)
      return {}
    })
    .catch((error) => {
      console.error("Failed to load task config:", error)
      return {}
    })
}

export function saveTaskConfig(config: TaskConfig): Promise<boolean> {
  return fetch("/api/task-config", {
    method: "POST",
    body: JSON.stringify(config),
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      }
      console.error("Failed to save task config:", data.message)
      return false
    })
    .catch((error) => {
      console.error("Failed to save task config:", error)
      return false
    })
}

export function resetTaskConfig(): Promise<boolean> {
  return fetch("/api/task-config", {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  })
    .then((res) => res.json())
    .then((data: ApiResponse) => {
      if (data.status === "success") {
        return true
      }
      console.error("Failed to reset task config:", data.message)
      return false
    })
    .catch((error) => {
      console.error("Failed to reset task config:", error)
      return false
    })
}
