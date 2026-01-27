import { defineStore } from "pinia"
import { ref, computed } from "vue"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  ScheduledTaskUpdate,
  TaskExecution,
} from "../types/scheduler"
import {
  getSchedulerTasks,
  createSchedulerTask,
  updateSchedulerTask,
  deleteSchedulerTask,
  pauseSchedulerTask,
  resumeSchedulerTask,
  getSchedulerExecutions,
} from "../script/api"

export const useSchedulerStore = defineStore("scheduler", () => {
  // State
  const tasks = ref<ScheduledTask[]>([])
  const executions = ref<TaskExecution[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Computed
  const enabledTasks = computed(() => tasks.value.filter((t) => t.enabled))
  const disabledTasks = computed(() => tasks.value.filter((t) => !t.enabled))
  const recentExecutions = computed(() => executions.value.slice(0, 50))

  // Actions
  async function fetchTasks() {
    loading.value = true
    error.value = null
    try {
      const response = await getSchedulerTasks()
      if (response.status === "success" && response.tasks) {
        tasks.value = response.tasks
      } else {
        error.value = response.message || "获取任务列表失败"
      }
    } catch (e) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to fetch tasks:", e)
    } finally {
      loading.value = false
    }
  }

  async function createTask(task: ScheduledTaskCreate) {
    loading.value = true
    error.value = null
    try {
      const response = await createSchedulerTask(task)
      if (response.status === "success" && response.task) {
        tasks.value.push(response.task)
        return true
      } else {
        error.value = response.message || "创建任务失败"
        return false
      }
    } catch (e) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to create task:", e)
      return false
    } finally {
      loading.value = false
    }
  }

  async function updateTask(taskId: string, taskUpdate: ScheduledTaskUpdate) {
    loading.value = true
    error.value = null
    try {
      const response = await updateSchedulerTask(taskId, taskUpdate)
      if (response.status === "success" && response.task) {
        const index = tasks.value.findIndex((t) => t.id === taskId)
        if (index !== -1) {
          tasks.value[index] = response.task
        }
        return true
      } else {
        error.value = response.message || "更新任务失败"
        return false
      }
    } catch (e) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to update task:", e)
      return false
    } finally {
      loading.value = false
    }
  }

  async function deleteTask(taskId: string) {
    loading.value = true
    error.value = null
    try {
      const response = await deleteSchedulerTask(taskId)
      if (response.status === "success") {
        tasks.value = tasks.value.filter((t) => t.id !== taskId)
        return true
      } else {
        error.value = response.message || "删除任务失败"
        return false
      }
    } catch (e) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to delete task:", e)
      return false
    } finally {
      loading.value = false
    }
  }

  async function toggleTask(taskId: string, enabled: boolean) {
    loading.value = true
    error.value = null
    try {
      const response = enabled
        ? await resumeSchedulerTask(taskId)
        : await pauseSchedulerTask(taskId)
      if (response.status === "success") {
        const task = tasks.value.find((t) => t.id === taskId)
        if (task) {
          task.enabled = enabled
        }
        return true
      } else {
        error.value = response.message || (enabled ? "启用任务失败" : "暂停任务失败")
        return false
      }
    } catch (e) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to toggle task:", e)
      return false
    } finally {
      loading.value = false
    }
  }

  async function fetchExecutions(limit: number = 50) {
    loading.value = true
    error.value = null
    try {
      const response = await getSchedulerExecutions(limit)
      if (response.status === "success" && response.executions) {
        executions.value = response.executions
      } else {
        error.value = response.message || "获取执行历史失败"
      }
    } catch (e) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to fetch executions:", e)
    } finally {
      loading.value = false
    }
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
    disabledTasks,
    recentExecutions,
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
