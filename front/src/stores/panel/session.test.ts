import { describe, expect, it, beforeEach } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import { useIndexStore } from "@/stores/panel/session"

describe("useIndexStore", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe("openTaskSettingsDrawer", () => {
    it("opens drawer with a task ID or preserves existing selection", () => {
      const store = useIndexStore()
      store.openTaskSettingsDrawer("task-456")
      expect(store.TaskSettingsDrawerVisible).toBe(true)
      expect(store.SelectedTaskID).toBe("task-456")

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
})
