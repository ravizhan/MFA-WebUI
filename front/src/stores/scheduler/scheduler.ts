import { defineStore } from "pinia"
import { ref, computed } from "vue"
import { tryCatch } from "@/utils/tryCatch"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  ScheduledTaskUpdate,
  TaskExecution,
} from "@/types/schedulerModel"
import {
  getSchedulerTasks,
  createSchedulerTask,
  updateSchedulerTask,
  deleteSchedulerTask,
  pauseSchedulerTask,
  resumeSchedulerTask,
  getSchedulerExecutions,
} from "@/services/api"

export const useSchedulerStore = defineStore("scheduler", () => {
  // State
  const tasks = ref<ScheduledTask[]>([])
  const executions = ref<TaskExecution[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Computed
  const enabledTasks = computed(() => tasks.value.filter((t) => t.enabled))

  // Actions
  async function fetchTasks() {
    loading.value = true
    error.value = null
    const [response, err] = await tryCatch(() => getSchedulerTasks())
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to fetch tasks:", err)
      loading.value = false
      return
    }
    if (response.status === "success" && response.tasks) {
      tasks.value = response.tasks
      loading.value = false
      return
    }
    error.value = response.message || "获取任务列表失败"
    loading.value = false
  }

  async function createTask(task: ScheduledTaskCreate): Promise<ScheduledTask | null> {
    loading.value = true
    error.value = null
    const [response, err] = await tryCatch(() => createSchedulerTask(task))
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to create task:", err)
      loading.value = false
      return null
    }
    if (response.status === "success" && response.task) {
      tasks.value.push(response.task)
      loading.value = false
      return response.task
    }
    error.value = response.message || "创建任务失败"
    loading.value = false
    return null
  }

  async function updateTask(taskId: string, taskUpdate: ScheduledTaskUpdate) {
    loading.value = true
    error.value = null
    const [response, err] = await tryCatch(() => updateSchedulerTask(taskId, taskUpdate))
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to update task:", err)
      loading.value = false
      return false
    }
    if (response.status === "success" && response.task) {
      const index = tasks.value.findIndex((t) => t.id === taskId)
      if (index !== -1) {
        tasks.value[index] = response.task
      }
      loading.value = false
      return true
    }
    error.value = response.message || "更新任务失败"
    loading.value = false
    return false
  }

  async function deleteTask(taskId: string) {
    loading.value = true
    error.value = null
    const [response, err] = await tryCatch(() => deleteSchedulerTask(taskId))
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to delete task:", err)
      loading.value = false
      return false
    }
    if (response.status === "success") {
      tasks.value = tasks.value.filter((t) => t.id !== taskId)
      loading.value = false
      return true
    }
    error.value = response.message || "删除任务失败"
    loading.value = false
    return false
  }

  async function toggleTask(taskId: string, enabled: boolean) {
    loading.value = true
    error.value = null
    const [response, err] = await tryCatch(() =>
      enabled ? resumeSchedulerTask(taskId) : pauseSchedulerTask(taskId),
    )
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to toggle task:", err)
      loading.value = false
      return false
    }
    if (response.status === "success") {
      const task = tasks.value.find((t) => t.id === taskId)
      if (task) {
        task.enabled = enabled
      }
      loading.value = false
      return true
    }
    error.value = response.message || (enabled ? "启用任务失败" : "暂停任务失败")
    loading.value = false
    return false
  }

  async function fetchExecutions(limit: number = 50) {
    loading.value = true
    error.value = null
    const [response, err] = await tryCatch(() => getSchedulerExecutions(limit))
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to fetch executions:", err)
      loading.value = false
      return
    }
    if (response.status === "success" && response.executions) {
      executions.value = response.executions
      loading.value = false
      return
    }
    error.value = response.message || "获取执行历史失败"
    loading.value = false
  }

  function getTaskById(taskId: string): ScheduledTask | undefined {
    return tasks.value.find((t) => t.id === taskId)
  }

  function clearError() {
    error.value = null
  }

  return {
    // State
    tasks,
    executions,
    loading,
    error,
    // Computed
    enabledTasks,
    // Actions
    fetchTasks,
    createTask,
    updateTask,
    deleteTask,
    toggleTask,
    fetchExecutions,
    getTaskById,
    clearError,
  }
})
