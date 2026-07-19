import { describe, expect, it, vi, beforeEach } from "vitest"
import { setActivePinia, createPinia } from "pinia"
import type { RealtimeEvent } from "@/types/realtimeModel"
import { dispatchRealtimeEvent, type RealtimeStoreRefs } from "@/services/realtime/dispatcher"
import { useIndexStore } from "@/stores/panel/session"
import { useSettingsStore } from "@/stores/settings/settings"

vi.mock("@/services/feedback/message", () => ({
  showGlobalMessage: vi.fn<() => void>(),
}))

vi.mock("@/services/realtime/events", () => ({
  formatRealtimeLog: vi.fn<(e: RealtimeEvent) => string>(
    (e: RealtimeEvent) => `${e.time} ${e.message}`,
  ),
  showToastMessage: vi.fn<() => void>(),
  showBrowserRealtimeNotification: vi.fn<() => void>(),
}))

import { showToastMessage, showBrowserRealtimeNotification } from "@/services/realtime/events"

const baseEvent: RealtimeEvent = {
  event: "log",
  level: "info",
  message: "hello",
  time: "2024-01-01T00:00:00Z",
  notify: [],
  display: true,
}

function makeStores(): RealtimeStoreRefs {
  return {
    indexStore: useIndexStore(),
    settingsStore: useSettingsStore(),
  }
}

describe("dispatchRealtimeEvent", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(showToastMessage).mockClear()
    vi.mocked(showBrowserRealtimeNotification).mockClear()
  })

  describe("display and channel gating", () => {
    it("appends to log only when display=true", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent }, stores)
      expect(stores.indexStore.RunningLog).toContain("hello")

      setActivePinia(createPinia())
      const stores2 = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, display: false }, stores2)
      expect(stores2.indexStore.RunningLog).toBe("")
    })

    it("gates toast and notification channels without duplication", () => {
      const stores = makeStores()

      dispatchRealtimeEvent({ ...baseEvent, notify: [] }, stores)
      expect(showToastMessage).not.toHaveBeenCalled()
      expect(showBrowserRealtimeNotification).not.toHaveBeenCalled()

      dispatchRealtimeEvent({ ...baseEvent, notify: ["toast"] }, stores)
      expect(showToastMessage).toHaveBeenCalledTimes(1)
      expect(showBrowserRealtimeNotification).not.toHaveBeenCalled()

      dispatchRealtimeEvent({ ...baseEvent, notify: ["notification"] }, stores)
      expect(showToastMessage).toHaveBeenCalledTimes(1)
      expect(showBrowserRealtimeNotification).toHaveBeenCalledTimes(1)

      dispatchRealtimeEvent({ ...baseEvent, notify: ["toast", "notification"] }, stores)
      expect(showToastMessage).toHaveBeenCalledTimes(2)
      expect(showBrowserRealtimeNotification).toHaveBeenCalledTimes(2)
    })
  })

  describe("task lifecycle dispatch", () => {
    it("sets TaskRunning for started/completed/failed while applying common handling", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, event: "task.started", notify: ["toast"] }, stores)
      expect(stores.indexStore.TaskRunning).toBe(true)
      expect(stores.indexStore.RunningLog).toContain("hello")
      expect(showToastMessage).toHaveBeenCalledTimes(1)

      dispatchRealtimeEvent({ ...baseEvent, event: "task.completed" }, stores)
      expect(stores.indexStore.TaskRunning).toBe(false)

      stores.indexStore.setTaskRunning(true)
      dispatchRealtimeEvent({ ...baseEvent, event: "task.failed" }, stores)
      expect(stores.indexStore.TaskRunning).toBe(false)
    })
  })

  describe("non-task events fall through to common handler", () => {
    it("focus.display gets log + toast without changing TaskRunning", () => {
      const stores = makeStores()
      dispatchRealtimeEvent({ ...baseEvent, event: "focus.display", notify: ["toast"] }, stores)
      expect(stores.indexStore.RunningLog).toContain("hello")
      expect(showToastMessage).toHaveBeenCalledTimes(1)
      expect(stores.indexStore.TaskRunning).toBe(false)
    })
  })
})
