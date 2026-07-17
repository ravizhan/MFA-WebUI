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
  getSystemCapabilities: vi.fn<() => void>(),
}))

import { useSchedulerStore } from "@/stores/scheduler/scheduler"
import * as api from "@/services/api"
import type { ScheduledTask, TaskExecution, SystemTaskRegistration, SystemTaskStatus } from "@/types/schedulerModel"

const mockTask = (id: string, enabled: boolean): ScheduledTask => ({
  id,
  name: `task-${id}`,
  enabled,
  task_list: [],
  task_options: {},
  preTasks: [],
  trigger_type: "cron",
  trigger_config: { type: "cron", cron: "* * * * *" },
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
})

function mockRegistration(overrides: Partial<SystemTaskRegistration> = {}): SystemTaskRegistration {
  return {
    task_id: "t1",
    task_name: "Test Task",
    platform: "windows",
    scope: "user",
    system_task_identifier: "mwutask-t1",
    trigger_spec: { trigger_type: "cron" as const, cron_expression: "0 9 * * *" },
    registered_exe_path: "C:\\mwustub.exe",
    last_registered_at: "2024-01-01T00:00:00Z",
    orphaned: false,
    state: "active",
    pending_operation: "none",
    desired_scope: "user",
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
        tasks: [mockTask("1", true)],
      })
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.tasks).toHaveLength(1)
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
      const created = mockTask("new", true)
      vi.mocked(api.createSchedulerTask).mockResolvedValue({
        status: "success",
        task: created,
      })
      const store = useSchedulerStore()
      const result = await store.createTask({
        name: "new",
        enabled: true,
        task_list: [],
        task_options: {},
        preTasks: [],
        trigger_type: "cron",
        trigger_config: { type: "cron", cron: "* * * * *" },
      })
      expect(result).toEqual(created)
      expect(store.tasks).toContainEqual(created)
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
      const updated = { ...original, name: "updated" }
      const store = useSchedulerStore()
      store.tasks = [original]
      vi.mocked(api.updateSchedulerTask).mockResolvedValue({
        status: "success",
        task: updated,
      })
      const result = await store.updateTask("1", { name: "updated" })
      expect(result).toBe(true)
      expect(store.tasks[0].name).toBe("updated")
    })

    it("syncs native_status into systemTaskStatuses on success", async () => {
      const original = mockTask("1", true)
      const updated = { ...original, name: "updated" }
      const nativeStatus: SystemTaskStatus = {
        task_id: "1",
        registered: true,
        path_valid: true,
        state: "active",
        scope: "user",
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

    it("normalizes last_known_scope in native_status", async () => {
      const original = mockTask("1", true)
      const updated = { ...original, name: "updated" }
      const nativeStatus: SystemTaskStatus = {
        task_id: "1",
        registered: true,
        path_valid: true,
        state: "active",
        last_known_scope: "system",
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
      expect(store.systemTaskStatuses["1"].scope).toBe("system")
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
      it("maps authoritative registration fields into status", async () => {
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "success",
          registrations: [
            mockRegistration({
              task_id: "t1",
              state: "active",
              orphaned: false,
              platform: "windows",
              scope: "user",
              desired_scope: "user",
              registered: true,
              path_valid: true,
              verified: true,
              observed: [
                {
                  scope: "user",
                  identifier: "test",
                  present: true,
                  verified: true,
                  details: "verified",
                },
              ],
              warnings: [],
            }),
            mockRegistration({
              task_id: "t2",
              state: "orphaned",
              orphaned: true,
              registered: false,
              path_valid: false,
              last_error: "APScheduler task removed",
            }),
            // state=active but authoritative registered=false (APS missing)
            mockRegistration({
              task_id: "t3",
              state: "active",
              orphaned: false,
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
        expect(active.orphaned).toBe(false)
        expect(active.observed).toHaveLength(1)
        expect(active.observed![0].present).toBe(true)

        const orphaned = store.systemTaskStatuses["t2"]
        expect(orphaned.registered).toBe(false)
        expect(orphaned.orphaned).toBe(true)
        expect(orphaned.state).toBe("orphaned")
        expect(orphaned.path_valid).toBe(false)

        const missing = store.systemTaskStatuses["t3"]
        expect(missing.registered).toBe(false)
        expect(missing.path_valid).toBe(false)
        expect(missing.reason).toBe("APS job missing")
      })

      it("does not synthesize success for error state", async () => {
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "success",
          registrations: [
            mockRegistration({
              task_id: "t-err",
              state: "error",
              orphaned: false,
              last_error: "native verification failed",
            }),
          ],
        })
        const store = useSchedulerStore()
        await store.fetchAllSystemStatuses()
        const errStatus = store.systemTaskStatuses["t-err"]
        expect(errStatus.registered).toBe(false)
        expect(errStatus.path_valid).toBe(false)
        expect(errStatus.state).toBe("error")
        expect(errStatus.last_error).toBe("native verification failed")
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

      it("resolves scope from last_known_scope over desired_scope and scope", async () => {
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "success",
          registrations: [
            mockRegistration({
              task_id: "t1",
              scope: "system",
              desired_scope: "user",
              last_known_scope: "user",
            }),
          ],
        })
        const store = useSchedulerStore()
        await store.fetchAllSystemStatuses()
        expect(store.systemTaskStatuses["t1"].scope).toBe("user")
      })

      it("falls back to desired_scope when last_known_scope absent", async () => {
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "success",
          registrations: [
            mockRegistration({
              task_id: "t1",
              scope: "system",
              desired_scope: "user",
              last_known_scope: undefined,
            }),
          ],
        })
        const store = useSchedulerStore()
        await store.fetchAllSystemStatuses()
        expect(store.systemTaskStatuses["t1"].scope).toBe("user")
      })

      it("falls back to scope when last_known_scope and desired_scope absent", async () => {
        vi.mocked(api.getSystemTasks).mockResolvedValue({
          status: "success",
          registrations: [
            mockRegistration({
              task_id: "t1",
              scope: "system",
              desired_scope: undefined,
            }),
          ],
        })
        const store = useSchedulerStore()
        await store.fetchAllSystemStatuses()
        expect(store.systemTaskStatuses["t1"].scope).toBe("system")
      })
    })

    describe("fetchSystemCapabilities", () => {
      it("populates systemCapabilities on success", async () => {
        const caps = {
          platform: "windows",
          cells: [
            {
              platform: "windows" as const,
              scope: "user" as const,
              trigger_type: "cron" as const,
              implemented: true,
              verified: true,
              enabled: true,
              reason: "ok",
              warnings: [],
            },
          ],
          system_scope_enabled: false,
          warnings: [],
        }
        vi.mocked(api.getSystemCapabilities).mockResolvedValue({ status: "success", data: caps })
        const store = useSchedulerStore()
        await store.fetchSystemCapabilities()
        expect(store.systemCapabilities).toEqual(caps)
      })

      it("keeps previous value on failure response", async () => {
        const prev = {
          platform: "windows",
          cells: [],
          system_scope_enabled: true,
          warnings: [],
        }
        const store = useSchedulerStore()
        store.systemCapabilities = prev
        vi.mocked(api.getSystemCapabilities).mockResolvedValue({
          status: "failed",
          message: "error",
        })
        await store.fetchSystemCapabilities()
        expect(store.systemCapabilities).toEqual(prev)
      })

      it("handles network error gracefully", async () => {
        vi.mocked(api.getSystemCapabilities).mockRejectedValue(new Error("net"))
        const store = useSchedulerStore()
        await store.fetchSystemCapabilities()
        expect(store.systemCapabilities).toBeNull()
      })
    })

    describe("getCapabilityCell", () => {
      it("returns matching cell", () => {
        const store = useSchedulerStore()
        store.systemCapabilities = {
          platform: "windows",
          cells: [
            {
              platform: "windows",
              scope: "user",
              trigger_type: "cron",
              implemented: true,
              verified: true,
              enabled: true,
              reason: "ok",
              warnings: [],
            },
            {
              platform: "windows",
              scope: "system",
              trigger_type: "cron",
              implemented: true,
              verified: false,
              enabled: false,
              reason: "needs elevation",
              warnings: ["requires admin"],
            },
          ],
          system_scope_enabled: false,
          warnings: [],
        }
        const cell = store.getCapabilityCell("windows", "user", "cron")
        expect(cell).toBeDefined()
        expect(cell!.enabled).toBe(true)
        expect(cell!.scope).toBe("user")
      })

      it("returns undefined for unknown cell", () => {
        const store = useSchedulerStore()
        store.systemCapabilities = {
          platform: "windows",
          cells: [],
          system_scope_enabled: false,
          warnings: [],
        }
        expect(store.getCapabilityCell("windows", "user", "date")).toBeUndefined()
      })

      it("returns undefined when capabilities not loaded", () => {
        const store = useSchedulerStore()
        expect(store.getCapabilityCell("windows", "user", "cron")).toBeUndefined()
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
