import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import type { RealtimeEvent } from "@/types/realtimeModel"
import type { NotificationSettings } from "@/types/settingsModel"
import {
  formatRealtimeLog,
  showToastMessage,
  showBrowserRealtimeNotification,
} from "@/services/realtime/events"

vi.mock("@/services/feedback/message", () => ({
  showGlobalMessage: vi.fn<() => void>(),
}))

import { showGlobalMessage } from "@/services/feedback/message"

const baseEvent: RealtimeEvent = {
  event: "log",
  level: "info",
  message: "hello",
  time: "2024-01-01T00:00:00Z",
  notify: [],
  display: true,
}

function notificationSettings(overrides: Partial<NotificationSettings> = {}): NotificationSettings {
  return {
    systemNotification: false,
    browserNotification: false,
    externalNotification: false,
    webhook: "",
    contentType: "application/json",
    headers: "",
    body: "",
    username: "",
    password: "",
    method: "POST",
    notifyOnComplete: false,
    notifyOnError: false,
    ...overrides,
  }
}

describe("formatRealtimeLog", () => {
  it("formats with time when present and message-only when absent", () => {
    expect(formatRealtimeLog(baseEvent)).toBe("2024-01-01T00:00:00Z hello")
    expect(formatRealtimeLog({ ...baseEvent, time: "" })).toBe("hello")
  })
})

describe("showToastMessage", () => {
  beforeEach(() => {
    vi.mocked(showGlobalMessage).mockClear()
  })

  it("maps event level to toast type", () => {
    showToastMessage({ ...baseEvent, level: "error" })
    expect(showGlobalMessage).toHaveBeenCalledWith("error", "hello")

    showToastMessage({ ...baseEvent, level: "success" })
    expect(showGlobalMessage).toHaveBeenCalledWith("success", "hello")
  })
})

describe("showBrowserRealtimeNotification", () => {
  const notificationMock = vi.fn<() => void>()

  beforeEach(() => {
    notificationMock.mockClear()
    vi.stubGlobal("Notification", notificationMock)
    Object.defineProperty(Notification, "permission", {
      value: "granted",
      configurable: true,
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("does nothing when browserNotification is disabled or permission is not granted", () => {
    showBrowserRealtimeNotification(baseEvent, notificationSettings())
    expect(notificationMock).not.toHaveBeenCalled()

    Object.defineProperty(Notification, "permission", {
      value: "default",
      configurable: true,
    })
    showBrowserRealtimeNotification(baseEvent, notificationSettings({ browserNotification: true }))
    expect(notificationMock).not.toHaveBeenCalled()
  })

  it("creates a notification with title fallback when enabled and granted", () => {
    const settings = notificationSettings({ browserNotification: true })
    showBrowserRealtimeNotification(baseEvent, settings)
    expect(notificationMock).toHaveBeenCalledWith("MWU", {
      body: "hello",
      tag: "log:2024-01-01T00:00:00Z",
    })

    showBrowserRealtimeNotification({ ...baseEvent, title: "NotifyTitle" }, settings)
    expect(notificationMock).toHaveBeenCalledWith("NotifyTitle", {
      body: "hello",
      tag: "log:2024-01-01T00:00:00Z",
    })
  })
})
