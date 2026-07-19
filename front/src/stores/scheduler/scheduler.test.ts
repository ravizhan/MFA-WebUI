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
}))

import { useSchedulerStore } from "@/stores/scheduler/scheduler"
import * as api from "@/services/api"
import type { ScheduledTask, TaskExecution } from "@/types/schedulerModel"

const mockTask = (id: string, enabled: boolean, wakeupEnabled = false): ScheduledTask => ({
  id,
  name: `task-${id}`,
  enabled,
  wakeup_enabled: wakeupEnabled,
  task_list: [],
  task_options: {},
  preTasks: [],
  trigger_config: { type: "cron", cron: "* * * * *" },
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
})

describe("useSchedulerStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  describe("fetchTasks", () => {
    it("sets tasks on success and maps error on failure/network", async () => {
      vi.mocked(api.getSchedulerTasks).mockResolvedValueOnce({
        status: "success",
        tasks: [mockTask("1", true, true)],
      })
      const store = useSchedulerStore()
      await store.fetchTasks()
      expect(store.tasks).toHaveLength(1)
      expect(store.tasks[0].wakeup_enabled).toBe(true)
      expect(store.error).toBeNull()

      vi.mocked(api.getSchedulerTasks).mockResolvedValueOnce({
        status: "failed",
        message: "load failed",
      })
      await store.fetchTasks()
      expect(store.error).toBe("load failed")

      vi.mocked(api.getSchedulerTasks).mockRejectedValueOnce(new Error("network"))
      await store.fetchTasks()
      expect(store.error).toBe("网络错误，请稍后重试")
    })
  })

  describe("createTask", () => {
    it("pushes task on success and returns null on failure", async () => {
      const created = mockTask("new", true, true)
      vi.mocked(api.createSchedulerTask).mockResolvedValueOnce({
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
        trigger_config: { type: "cron", cron: "* * * * *" },
      })
      expect(result).toEqual(created)
      expect(store.tasks).toContainEqual(created)
      expect(api.createSchedulerTask).toHaveBeenCalledWith(
        expect.objectContaining({ wakeup_enabled: true }),
      )

      vi.mocked(api.createSchedulerTask).mockResolvedValueOnce({
        status: "failed",
        message: "create failed",
      })
      const failed = await store.createTask({
        name: "new",
        enabled: true,
        wakeup_enabled: false,
        task_list: [],
        task_options: {},
        preTasks: [],
        trigger_config: { type: "cron", cron: "* * * * *" },
      })
      expect(failed).toBeNull()
      expect(store.error).toBe("create failed")
    })
  })

  describe("updateTask", () => {
    it("updates task including wakeup_enabled and returns false on failure", async () => {
      const original = mockTask("1", true)
      const updated = { ...original, name: "updated", wakeup_enabled: true }
      const store = useSchedulerStore()
      store.tasks = [original]
      vi.mocked(api.updateSchedulerTask).mockResolvedValueOnce({
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

      vi.mocked(api.updateSchedulerTask).mockResolvedValueOnce({
        status: "success",
        task: { ...updated, wakeup_enabled: false },
      })
      await store.updateTask("1", { wakeup_enabled: false })
      expect(store.tasks[0].wakeup_enabled).toBe(false)
      expect(api.updateSchedulerTask).toHaveBeenCalledWith("1", { wakeup_enabled: false })

      vi.mocked(api.updateSchedulerTask).mockResolvedValueOnce({
        status: "failed",
        message: "update failed",
      })
      expect(await store.updateTask("1", { name: "x" })).toBe(false)
      expect(store.error).toBe("update failed")
    })
  })

  describe("deleteTask", () => {
    it("removes task on success and returns false on failure", async () => {
      vi.mocked(api.deleteSchedulerTask).mockResolvedValueOnce({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", true), mockTask("2", true)]
      expect(await store.deleteTask("1")).toBe(true)
      expect(store.tasks.map((t) => t.id)).toEqual(["2"])

      vi.mocked(api.deleteSchedulerTask).mockResolvedValueOnce({
        status: "failed",
        message: "delete failed",
      })
      expect(await store.deleteTask("2")).toBe(false)
      expect(store.error).toBe("delete failed")
    })
  })

  describe("toggleTask", () => {
    it("enables via resume and disables via pause", async () => {
      vi.mocked(api.resumeSchedulerTask).mockResolvedValue({ status: "success" })
      vi.mocked(api.pauseSchedulerTask).mockResolvedValue({ status: "success" })
      const store = useSchedulerStore()
      store.tasks = [mockTask("1", false)]

      expect(await store.toggleTask("1", true)).toBe(true)
      expect(api.resumeSchedulerTask).toHaveBeenCalledWith("1")
      expect(store.tasks[0].enabled).toBe(true)

      expect(await store.toggleTask("1", false)).toBe(true)
      expect(api.pauseSchedulerTask).toHaveBeenCalledWith("1")
      expect(store.tasks[0].enabled).toBe(false)
    })
  })

  describe("fetchExecutions", () => {
    it("sets executions on success and error on failure", async () => {
      const executions: TaskExecution[] = [
        {
          id: "e1",
          task_id: "1",
          task_name: "task-1",
          origin: "manual",
          occurrence_id: null,
          scheduled_for: null,
          started_at: "2024-01-01T00:00:00Z",
          finished_at: null,
          status: "success",
          blocker_run_id: null,
          blocker_task_name: null,
          error_message: null,
        },
      ]
      vi.mocked(api.getSchedulerExecutions).mockResolvedValueOnce({
        status: "success",
        executions,
      })
      const store = useSchedulerStore()
      await store.fetchExecutions(10)
      expect(api.getSchedulerExecutions).toHaveBeenCalledWith(10)
      expect(store.executions).toEqual(executions)

      vi.mocked(api.getSchedulerExecutions).mockResolvedValueOnce({
        status: "failed",
        message: "history failed",
      })
      await store.fetchExecutions()
      expect(store.error).toBe("history failed")
    })
  })
})
