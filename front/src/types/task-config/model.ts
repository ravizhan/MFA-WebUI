import type { ComputedRef } from "vue"
import type { TaskOptionValue } from "@/types/scheduler/model"

export interface TaskListItem {
  id: string
  name: string
  order: number
  checked?: boolean
}

export interface TaskConfig {
  taskList: string[]
  taskChecked?: Record<string, boolean>
  taskOptions: Record<string, TaskOptionValue>
}

export interface TaskConfigState {
  availableTasks: TaskListItem[]
  selectedTasks: string[]
  currentConfigTaskId: string | null
  taskOptions: Record<string, TaskOptionValue>
}

export interface TaskConfigActions {
  toggleTask: (taskId: string, checked: boolean) => void
  setCurrentConfigTask: (taskId: string | null) => void
  updateTaskOption: (key: string, value: TaskOptionValue) => void
  updateTaskOptions: (options: Record<string, TaskOptionValue>) => void
  getSelectedTasks: () => string[]
  getTaskConfig: () => TaskConfig
  initFromConfig: (config: Partial<TaskConfig>) => void
  reset: () => void
}

export interface UseTaskConfigReturn {
  state: TaskConfigState
  actions: TaskConfigActions
  currentTaskOptions: ComputedRef<string[]>
  currentTaskName: ComputedRef<string>
}
