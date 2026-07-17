import { describe, expect, it, beforeEach, vi } from "vitest"
import { setActivePinia, createPinia } from "pinia"

vi.mock("@/services/api", () => ({
  getSchedulerTasks: vi.fn<() => void>(),
  createSchedulerTask: vi.fn<() => void>(),
  updateSchedulerTask: vi.fn<() => void>(),
  deleteSchedulerTask: vi.fn<() => void>(),
  pauseSchedulerTask: vi.fn<() => void>(),
  resumeSchedulerTask: vi.fn<() => void>(),
  getSchedulerExecutions: vi.fn<() => void>(),
  getSystemTaskStatus: vi.fn<() => void>(),
  getSystemTasks: vi.fn<() => void>(),
  repairSystemTasks: vi.fn<() => void>(),
}))

import { useSchedulerStore } from "@/stores/scheduler/scheduler"
import * as api from "@/services/api"
import type {
  ScheduledTask,
  TaskExecution,
  SystemTaskRegistration,
  SystemTaskStatus,
} from "@/types/schedulerModel"

const mockTask = (id: string, enabled: boolean, wakeupEnabled = false): ScheduledTask => ({
  id,
  name: `task-${id}`,
  enabled,
  wakeup_enabled: wakeupEnabled,
  task_list: [],
  task_options: {},
  preTasks: [],
  trigger_type: "cron",
  trigger_config: { type: "cron", cron: "* * * * *" },
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
})

function mockRegistration(
  overrides: Partial<SystemTaskRegistration> = {},
): SystemTaskRegistration {
  return {
    task_id: "t1",
    task_name: "Test Task",
    platform: "windows",
    state: "active",
    registered: true,
    enabled: true,
    verified: true,
    path_valid: true,
    registered_exe_path: "C:\\mwustub.exe",
    trigger: { trigger_type: "cron", cron_expression: "0 9 * * *" },
    ...overrides,
  }
}

describe("useSchedulerStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("has correct initial state", () => {
    const store = useSchedulerStore()
    expect(store.tasks).toEqual([])
    expect(store.executions).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  describe("enabledTasks getter", () => {
    it("filters only enabled tasks", () => {
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true), mockTask("2", false), mockTask("3", true)]
      expect(store.enabledTasks).toHaveLength(2)
      expect(store.enabledTasks.map((t) => t.id)).toEqual(["1", "3"])
    })
  })

  describe("fetchTasks", () => {
    it("sets tasks on success", async () => {
      vi.mocked(api.getSchedulerTasks).mockResolvedValue({
        status: "success",
        tasks: [mockTask("1", true, true)],
      })
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.tasks).toHaveLength(1)
      expect(store.tasks[0].wakeup_enabled).toBe(true)
      expect(store.error).toBeNull()
    })

    it("sets error on failure response", async () => {
      vi.mocked(api.getSchedulerTasks).mockResolvedValue({
        status: "failed",
        message: "load failed",
      })
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.tasks).toEqual([])
      expect(store.error).toBe("load failed")
    })

    it("sets network error on exception", async () => {
      vi.mocked(api.getSchedulerTasks).mockRejectedValue(new Error("network"))
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.error).toBe("网络错误，请稍后重试")
    })
  })

  describe("createTask", () => {
    it("pushes task and returns created task on success", async () => {
      const created = mockTask("new", true, true)
      vi.mocked(api.createSchedulerTask).mockResolvedValue({
        status: "success",
        task: created,
      })
      const store = useSchedulerStore()
      const result = await store.createTask({
        name: "new",
        enabled: true,
        wakeup_enabled: true,
        task_list: [],
        task_options: {},
        preTasks: [],
        trigger_type: "cron",
        trigger_config: { type: "cron", cron: "* * * * *" },
      })
      expect(result).toEqual(created)
      expect(store.tasks).toContainEqual(created)
      expect(api.createSchedulerTask).toHaveBeenCalledWith(
        expect.objectContaining({ wakeup_enabled: true }),
      )
    })

    it("sets error and returns null on failure", async () => {
      vi.mocked(api.createSchedulerTask).mockResolvedValue({
        status: "failed",
        message: "create failed",
      })
      const store = useSchedulerStore()
      const result = await store.createTask({
        name: "new",
        enabled: true,
        wakeup_enabled: false,
        task_list: [],
        task_options: {},
        preTasks: [],
        trigger_type: "cron",
        trigger_config: { type: "cron", cron: "* * * * *" },
      })
      expect(result).toBeNull()
      expect(store.error).toBe("create failed")
    })
  })

  describe("updateTask", () => {
    it("updates task in list and returns true on success", async () => {
      const original = mockTask("1", true)
      const updated = { ...original, name: "updated", wakeup_enabled: true }
      const store = useSchedulerStore()
      store.tasks = [original]
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "success",
        task: updated,
      })
      const result = await store.updateTask("1", { name: "updated", wakeup_enabled: true })
      expect(result).toBe(true)
      expect(store.tasks[0].name).toBe("updated")
      expect(store.tasks[0].wakeup_enabled).toBe(true)
      expect(api.updateSchedulerTask).toHaveBeenCalledWith("1", {
        name: "updated",
        wakeup_enabled: true,
      })
    })

    it("sends wakeup_enabled false to disable native wakeup", async () => {
      const original = mockTask("1", true, true)
      const updated = { ...original, wakeup_enabled: false }
      const store = useSchedulerStore()
      store.tasks = [original]
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "success",
        task: updated,
      })
      const result = await store.updateTask("1", { wakeup_enabled: false })
      expect(result).toBe(true)
      expect(store.tasks[0].wakeup_enabled).toBe(false)
      expect(api.updateSchedulerTask).toHaveBeenCalledWith("1", { wakeup_enabled: false })
    })

    it("syncs native_status into systemTaskStatuses on success", async () => {
      const original = mockTask("1", true, true)
      const updated = { ...original, name: "updated" }
      const nativeStatus: SystemTaskStatus = {
        task_id: "1",
        registered: true,
        path_valid: true,
        state: "active",
        enabled: true,
        verified: true,
      }
      const store = useSchedulerStore()
      store.tasks = [original]
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "success",
        task: updated,
        native_status: nativeStatus,
      })
      const result = await store.updateTask("1", { name: "updated" })
      expect(result).toBe(true)
      expect(store.systemTaskStatuses["1"]).toEqual(nativeStatus)
    })

    it("stores synthetic error status on native_error without failing", async () => {
      const original = mockTask("1", true)
      const updated = { ...original, name: "updated" }
      const store = useSchedulerStore()
      store.tasks = [original]
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "success",
        task: updated,
        native_error: "native failure",
      })
      const result = await store.updateTask("1", { name: "updated" })
      expect(result).toBe(true)
      expect(store.tasks[0].name).toBe("updated")
      expect(store.systemTaskStatuses["1"]).toEqual({
        task_id: "1",
        registered: false,
        path_valid: false,
        state: "error",
        last_error: "native failure",
      })
    })

    it("preserves existing systemTaskStatuses when native fields absent", async () => {
      const original = mockTask("1", true)
      const updated = { ...original, name: "updated" }
      const store = useSchedulerStore()
      store.tasks = [original]
      store.systemTaskStatuses = {
        "1": { task_id: "1", registered: true, path_valid: true, state: "active" },
      }
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "success",
        task: updated,
      })
      const result = await store.updateTask("1", { name: "updated" })
      expect(result).toBe(true)
      expect(store.systemTaskStatuses["1"].state).toBe("active")
    })

    it("returns false on failure", async () => {
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "failed",
        message: "update failed",
      })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true)]
      const result = await store.updateTask("1", { name: "updated" })
      expect(result).toBe(false)
      expect(store.error).toBe("update failed")
    })
  })

  describe("deleteTask", () => {
    it("removes task and returns true on success", async () => {
      vi.mocked(api.deleteSchedulerTask).mockResolvedValue({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true), mockTask("2", true)]
      const result = await store.deleteTask("1")
      expect(result).toBe(true)
      expect(store.tasks.map((t) => t.id)).toEqual(["2"])
    })

    it("returns false on failure", async () => {
      vi.mocked(api.deleteSchedulerTask).mockResolvedValue({
        status: "failed",
        message: "delete failed",
      })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true)]
      const result = await store.deleteTask("1")
      expect(result).toBe(false)
      expect(store.error).toBe("delete failed")
    })
  })

  describe("toggleTask", () => {
    it("enables task by calling resumeSchedulerTask", async () => {
      vi.mocked(api.resumeSchedulerTask).mockResolvedValue({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", false)]
      const result = await store.toggleTask("1", true)
      expect(api.resumeSchedulerTask).toHaveBeenCalledWith("1")
      expect(result).toBe(true)
      expect(store.tasks[0].enabled).toBe(true)
    })

    it("disables task by calling pauseSchedulerTask", async () => {
      vi.mocked(api.pauseSchedulerTask).mockResolvedValue({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true)]
      const result = await store.toggleTask("1", false)
      expect(api.pauseSchedulerTask).toHaveBeenCalledWith("1")
      expect(result).toBe(true)
      expect(store.tasks[0].enabled).toBe(false)
    })
  })

  describe("fetchExecutions", () => {
    it("sets executions on success", async () => {
      const executions: TaskExecution[] = [
        {
          id: "e1",
          task_id: "1",
          task_name: "task-1",
          started_at: "2024-01-01T00:00:00Z",
          status: "success",
        },
      ]
      vi.mocked(api.getSchedulerExecutions).mockResolvedValue({
        status: "success",
        executions,
      })
      const store = useSchedulerStore()
      await store.fetchExecutions(10)
      expect(api.getSchedulerExecutions).toHaveBeenCalledWith(10)
      expect(store.executions).toEqual(executions)
    })

    it("sets error on failure", async () => {
      vi.mocked(api.getSchedulerExecutions).mockResolvedValue({
        status: "failed",
        message: "history failed",
      })
      const store = useSchedulerStore()
      await store.fetchExecutions()
      expect(store.error).toBe("history failed")
    })
  })

  describe("system-level scheduling", () => {
    describe("fetchAllSystemStatuses", () => {
      it("maps registration fields into status without scope fallback", async () => {
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "success",
          registrations: [
            mockRegistration({
              task_id: "t1",
              state: "active",
              registered: true,
              path_valid: true,
              verified: true,
              enabled: true,
            }),
            mockRegistration({
              task_id: "t2",
              state: "error",
              registered: false,
              path_valid: false,
              last_error: "native verification failed",
            }),
            mockRegistration({
              task_id: "t3",
              state: "active",
              registered: false,
              path_valid: false,
              reason: "APS job missing",
            }),
          ],
        })
        const store = useSchedulerStore()
        await store.fetchAllSystemStatuses()
        expect(Object.keys(store.systemTaskStatuses)).toHaveLength(3)

        const active = store.systemTaskStatuses["t1"]
        expect(active.registered).toBe(true)
        expect(active.path_valid).toBe(true)
        expect(active.state).toBe("active")
        expect(active.enabled).toBe(true)

        const err = store.systemTaskStatuses["t2"]
        expect(err.registered).toBe(false)
        expect(err.state).toBe("error")
        expect(err.last_error).toBe("native verification failed")

        const missing = store.systemTaskStatuses["t3"]
        expect(missing.registered).toBe(false)
        expect(missing.path_valid).toBe(false)
        expect(missing.reason).toBe("APS job missing")
      })

      it("does not populate statuses when backend responds with failure", async () => {
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "failed",
          message: "unavailable",
        })
        const store = useSchedulerStore()
        store.systemTaskStatuses = { t1: { task_id: "t1", registered: true, path_valid: true } }
        await store.fetchAllSystemStatuses()
        expect(store.systemTaskStatuses).toEqual({
          t1: { task_id: "t1", registered: true, path_valid: true },
        })
      })
    })

    describe("fetchSystemTaskStatus", () => {
      it("stores status for a single task", async () => {
        const status: SystemTaskStatus = {
          task_id: "t1",
          state: "active",
          registered: true,
          path_valid: true,
          enabled: true,
        }
        vi.mocked(api.getSystemTaskStatus).mockResolvedValue({
          status: "success",
          data: status,
        })
        const store = useSchedulerStore()
        await store.fetchSystemTaskStatus("t1")
        expect(store.systemTaskStatuses["t1"]).toEqual(status)
      })
    })

    describe("repairSystemTasksAll", () => {
      it("repairs then refreshes registrations and statuses", async () => {
        vi.mocked(api.repairSystemTasks).mockResolvedValue({
          status: "success",
          data: { repaired: 1, failed: 0, details: ["t1"] },
        })
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "success",
          registrations: [mockRegistration({ task_id: "t1" })],
        })
        const store = useSchedulerStore()
        const result = await store.repairSystemTasksAll()
        expect(result).toBe(true)
        expect(api.repairSystemTasks).toHaveBeenCalled()
        expect(api.getSystemTasks).toHaveBeenCalled()
        expect(store.systemRegistrations).toHaveLength(1)
        expect(store.systemTaskStatuses["t1"].state).toBe("active")
      })

      it("returns false on repair failure", async () => {
        vi.mocked(api.repairSystemTasks).mockResolvedValue({
          status: "failed",
          message: "repair failed",
        })
        const store = useSchedulerStore()
        const result = await store.repairSystemTasksAll()
        expect(result).toBe(false)
        expect(store.error).toBe("repair failed")
      })
    })

    describe("getSystemStatus", () => {
      it("returns status entry for known task", () => {
        const store = useSchedulerStore()
        store.systemTaskStatuses = { t1: { task_id: "t1", registered: true, path_valid: true } }
        expect(store.getSystemStatus("t1")).toBeDefined()
      })

      it("returns undefined for unknown task", () => {
        const store = useSchedulerStore()
        expect(store.getSystemStatus("unknown")).toBeUndefined()
      })
    })
  })
})
