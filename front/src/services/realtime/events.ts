import type { NotificationSettings } from "@/types/settingsModel"
import type { RealtimeEvent } from "@/types/realtimeModel"
import { showGlobalMessage } from "@/services/feedback/message"
import { tryCatch } from "@/utils/tryCatch"

function getToastType(level: string): "error" | "success" | "info" {
  if (level === "error") return "error"
  if (level === "success") return "success"
  return "info"
}

export function formatRealtimeLog(event: RealtimeEvent): string {
  return event.time ? `${event.time} ${event.message}` : event.message
}

export function showToastMessage(event: RealtimeEvent): void {
  showGlobalMessage(getToastType(event.level), event.message)
}

export function showBrowserRealtimeNotification(
  event: RealtimeEvent,
  settings: NotificationSettings,
): void {
  if (!settings.browserNotification) {
    return
  }
  if (typeof Notification === "undefined" || Notification.permission !== "granted") {
    return
  }

  const [, notifyErr] = tryCatch(() => {
    new Notification(event.title || "MWU", {
      body: event.message,
      tag: `${event.event}:${event.time}`,
    })
  })
  if (notifyErr) {
    console.error("浏览器通知发送失败:", notifyErr)
  }
}
