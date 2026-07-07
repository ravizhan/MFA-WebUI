import type { NotificationSettings } from "@/types/settings/model"
import type { RealtimeEvent } from "@/types/realtime/model"
import { showGlobalMessage } from "@/services/feedback/message"

function formatMessageContent(event: RealtimeEvent): string {
  return event.title ? `${event.title}: ${event.message}` : event.message
}

export function formatRealtimeLog(event: RealtimeEvent): string {
  return event.time ? `${event.time} ${event.message}` : event.message
}

export function showRealtimeMessage(event: RealtimeEvent): void {
  showGlobalMessage(event.level, formatMessageContent(event))
}

export function showToastMessage(event: RealtimeEvent): void {
  const type = event.level === "error" ? "error" : event.level === "success" ? "success" : "info"
  showGlobalMessage(type, event.message)
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

  try {
    new Notification(event.title || "MWU", {
      body: event.message,
      tag: `${event.event}:${event.time}`,
    })
  } catch (error) {
    console.error("浏览器通知发送失败:", error)
  }
}
