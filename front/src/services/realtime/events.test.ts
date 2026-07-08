import { describe, expect, it, vi, beforeEach, afterEach } from "vitest"
import type { RealtimeEvent } from "@/types/realtimeModel"
import type { NotificationSettings } from "@/types/settingsModel"
import {
  formatRealtimeLog,
  showRealtimeMessage,
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

describe("formatRealtimeLog", () => {
  it("returns time and message when time is present", () => {
    const event = { ...baseEvent }
    expect(formatRealtimeLog(event)).toBe("2024-01-01T00:00:00Z hello")
  })

  it("returns only message when time is absent", () => {
    const event = { ...baseEvent, time: "" }
    expect(formatRealtimeLog(event)).toBe("hello")
  })
})

describe("showRealtimeMessage", () => {
  beforeEach(() => {
    vi.mocked(showGlobalMessage).mockClear()
  })

  it("calls showGlobalMessage with level and title:message content", () => {
    const event: RealtimeEvent = { ...baseEvent, title: "Title" }
    showRealtimeMessage(event)
    expect(showGlobalMessage).toHaveBeenCalledWith("info", "Title: hello")
  })

  it("calls showGlobalMessage with level and message only when title is absent", () => {
    const event: RealtimeEvent = { ...baseEvent, title: null }
    showRealtimeMessage(event)
    expect(showGlobalMessage).toHaveBeenCalledWith("info", "hello")
  })
})

describe("showToastMessage", () => {
  beforeEach(() => {
    vi.mocked(showGlobalMessage).mockClear()
  })

  it.each([
    ["error", "error"],
    ["success", "success"],
    ["info", "info"],
  ] satisfies [RealtimeEvent["level"], "error" | "success" | "info"][])(
    "maps level %s to toast type %s",
    (level, expectedType) => {
      const event: RealtimeEvent = { ...baseEvent, level }
      showToastMessage(event)
      expect(showGlobalMessage).toHaveBeenCalledWith(expectedType, "hello")
    },
  )
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

  it("does nothing when browserNotification is disabled", () => {
    const settings: NotificationSettings = {
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
    }
    showBrowserRealtimeNotification(baseEvent, settings)
    expect(notificationMock).not.toHaveBeenCalled()
  })

  it("does nothing when Notification.permission is not granted", () => {
    Object.defineProperty(Notification, "permission", {
      value: "default",
      configurable: true,
    })
    const settings: NotificationSettings = {
      systemNotification: false,
      browserNotification: true,
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
    }
    showBrowserRealtimeNotification(baseEvent, settings)
    expect(notificationMock).not.toHaveBeenCalled()
  })

  it("creates a notification when enabled and permission is granted", () => {
    const settings: NotificationSettings = {
      systemNotification: false,
      browserNotification: true,
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
    }
    showBrowserRealtimeNotification(baseEvent, settings)
    expect(notificationMock).toHaveBeenCalledWith("MWU", {
      body: "hello",
      tag: "log:2024-01-01T00:00:00Z",
    })
  })

  it("uses event.title as notification title when present", () => {
    const settings: NotificationSettings = {
      systemNotification: false,
      browserNotification: true,
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
    }
    const event: RealtimeEvent = { ...baseEvent, title: "NotifyTitle" }
    showBrowserRealtimeNotification(event, settings)
    expect(notificationMock).toHaveBeenCalledWith("NotifyTitle", {
      body: "hello",
      tag: "log:2024-01-01T00:00:00Z",
    })
  })
})
