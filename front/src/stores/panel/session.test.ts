import { describe, expect, it, beforeEach } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import { useIndexStore } from "@/stores/panel/session"

describe("useIndexStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it("has correct initial state", () => {
    const store = useIndexStore()
    expect(store.SelectedTaskID).toBe("")
    expect(store.RunningLog).toBe("")
    expect(store.Connected).toBe(false)
    expect(store.TaskRunning).toBe(false)
    expect(store.TaskSettingsDrawerVisible).toBe(false)
  })

  describe("openTaskSettingsDrawer", () => {
    it("opens drawer with a task ID", () => {
      const store = useIndexStore()
      store.openTaskSettingsDrawer("task-456")
      expect(store.TaskSettingsDrawerVisible).toBe(true)
      expect(store.SelectedTaskID).toBe("task-456")
    })

    it("opens drawer without changing existing task ID", () => {
      const store = useIndexStore()
      store.SelectedTaskID = "existing-task"
      store.openTaskSettingsDrawer()
      expect(store.TaskSettingsDrawerVisible).toBe(true)
      expect(store.SelectedTaskID).toBe("existing-task")
    })
  })

  describe("UpdateLog", () => {
    it("appends multiple log lines with newline separators", () => {
      const store = useIndexStore()
      store.UpdateLog("line 1")
      store.UpdateLog("line 2")
      expect(store.RunningLog).toBe("line 1\nline 2\n")
    })
  })

  describe("setTaskRunning", () => {
    it("sets TaskRunning state", () => {
      const store = useIndexStore()
      store.setTaskRunning(true)
      expect(store.TaskRunning).toBe(true)
      store.setTaskRunning(false)
      expect(store.TaskRunning).toBe(false)
    })
  })
})
