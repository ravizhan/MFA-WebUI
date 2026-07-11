import { defineStore } from "pinia"
import { ref, computed } from "vue"
import { tryCatch } from "@/utils/tryCatch"
import type {
  ScheduledTask,
  ScheduledTaskCreate,
  ScheduledTaskUpdate,
  TaskExecution,
  SystemTaskStatus,
  SystemTaskRegistration,
  SystemTaskScope,
  SystemTaskCapabilities,
  SystemTaskCapabilityCell,
  SystemTaskObservation,
  TriggerType,
} from "@/types/schedulerModel"
import {
  getSchedulerTasks,
  createSchedulerTask,
  updateSchedulerTask,
  deleteSchedulerTask,
  pauseSchedulerTask,
  resumeSchedulerTask,
  getSchedulerExecutions,
  registerSystemTask,
  unregisterSystemTask,
  getSystemTaskStatus,
  getSystemTasks,
  repairSystemTasks,
  getSystemCapabilities,
} from "@/services/api"

export const useSchedulerStore = defineStore("scheduler", () => {
  // State
  const tasks = ref<ScheduledTask[]>([])
  const executions = ref<TaskExecution[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const systemTaskStatuses = ref<Record<string, SystemTaskStatus>>({})
  const systemRegistrations = ref<SystemTaskRegistration[]>([])
  const systemCapabilities = ref<SystemTaskCapabilities | null>(null)

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

  // System-level scheduling actions
  async function fetchSystemTaskStatus(taskId: string) {
    const [response, err] = await tryCatch(() => getSystemTaskStatus(taskId))
    if (err) {
      console.error("Failed to fetch system task status:", err)
      return
    }
    if (response.status === "success" && response.data) {
      systemTaskStatuses.value[taskId] = response.data
    }
  }

  async function registerSystem(taskId: string, scope: SystemTaskScope) {
    const [response, err] = await tryCatch(() => registerSystemTask(taskId, { scope }))
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to register system task:", err)
      return false
    }
    if (response.status === "success" && response.data) {
      systemTaskStatuses.value[taskId] = response.data
      return true
    }
    error.value = response.message || "系统级注册失败"
    return false
  }

  async function unregisterSystem(taskId: string) {
    const [response, err] = await tryCatch(() => unregisterSystemTask(taskId))
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to unregister system task:", err)
      return false
    }
    if (response.status === "success") {
      delete systemTaskStatuses.value[taskId]
      return true
    }
    error.value = response.message || "卸载系统级注册失败"
    return false
  }

  async function fetchSystemRegistrations() {
    const [response, err] = await tryCatch(() => getSystemTasks())
    if (err) {
      console.error("Failed to fetch system registrations:", err)
      return
    }
    if (response.status === "success" && response.registrations) {
      systemRegistrations.value = response.registrations
    }
  }

  async function fetchAllSystemStatuses() {
    const [response, err] = await tryCatch(() => getSystemTasks())
    if (err) {
      console.error("Failed to fetch system statuses:", err)
      return
    }
    if (response.status === "success" && response.registrations) {
      const statuses: Record<string, SystemTaskStatus> = {}
      for (const reg of response.registrations) {
        const isActive = reg.state === "active" || reg.state === "pending_register"
        const observed: SystemTaskObservation[] =
          reg.observed?.map((obs) => ({
            scope: obs.scope,
            registered: obs.registered,
            verified: obs.verified,
            native_present: obs.native_present,
            last_error: obs.last_error,
          })) ?? []
        statuses[reg.task_id] = {
          task_id: reg.task_id,
          registered: isActive && !reg.orphaned,
          scope: reg.scope,
          platform: reg.platform,
          path_valid: isActive,
          last_error: reg.last_error,
          state: reg.state,
          pending_operation: reg.pending_operation,
          orphaned: reg.orphaned,
          desired_scope: reg.desired_scope,
          observed,
          warnings: reg.warnings,
        }
      }
      systemTaskStatuses.value = statuses
    }
  }

  async function repairSystemTasksAll() {
    loading.value = true
    error.value = null
    const [response, err] = await tryCatch(() => repairSystemTasks())
    if (err) {
      error.value = "网络错误，请稍后重试"
      console.error("Failed to repair system tasks:", err)
      loading.value = false
      return false
    }
    if (response.status === "success") {
      await fetchSystemRegistrations()
      await fetchAllSystemStatuses()
      loading.value = false
      return true
    }
    error.value = response.message || "修复失败"
    loading.value = false
    return false
  }

  async function fetchSystemCapabilities() {
    const [response, err] = await tryCatch(() => getSystemCapabilities())
    if (err) {
      console.error("Failed to fetch system capabilities:", err)
      return
    }
    if (response.status === "success" && response.data) {
      systemCapabilities.value = response.data
    }
  }

  function getCapabilityCell(
    platform: string,
    scope: SystemTaskScope,
    triggerType: TriggerType,
  ): SystemTaskCapabilityCell | undefined {
    return systemCapabilities.value?.cells.find(
      (c) => c.platform === platform && c.scope === scope && c.trigger_type === triggerType,
    )
  }

  function getSystemStatus(taskId: string): SystemTaskStatus | undefined {
    return systemTaskStatuses.value[taskId]
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
    systemTaskStatuses,
    systemRegistrations,
    systemCapabilities,
    // Computed
    enabledTasks,
    // Actions
    fetchTasks,
    createTask,
    updateTask,
    deleteTask,
    toggleTask,
    fetchExecutions,
    fetchSystemTaskStatus,
    registerSystem,
    unregisterSystem,
    fetchSystemRegistrations,
    fetchAllSystemStatuses,
    repairSystemTasksAll,
    fetchSystemCapabilities,
    getCapabilityCell,
    getSystemStatus,
    getTaskById,
    clearError,
  }
})
