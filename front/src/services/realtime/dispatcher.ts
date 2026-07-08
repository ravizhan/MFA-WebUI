import type { RealtimeEvent, RealtimeEventName } from "@/types/realtime/model"
import type { useIndexStore } from "@/stores/panel/session"
import type { useSettingsStore } from "@/stores/settings/settings"
import { formatRealtimeLog, showBrowserRealtimeNotification, showToastMessage } from "./events"

export interface RealtimeStoreRefs {
  indexStore: ReturnType<typeof useIndexStore>
  settingsStore: ReturnType<typeof useSettingsStore>
}

/**
 * Common handling for every SSE event:
 * 1. Append to the running log panel (if display=true)
 * 2. Show an in-app toast (if notify includes "toast")
 * 3. Show a browser Notification (if notify includes "notification")
 *
 * This replaces the old handleRealtimeEvent which had a double-notification
 * bug: it called showRealtimeMessage() unconditionally for any non-empty
 * notify array, duplicating the toast already shown by showToastMessage().
 */
function handleCommon(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  if (event.display) {
    stores.indexStore.UpdateLog(formatRealtimeLog(event))
  }
  if (event.notify.includes("toast")) {
    showToastMessage(event)
  }
  if (event.notify.includes("notification")) {
    showBrowserRealtimeNotification(event, stores.settingsStore.settings.notification)
  }
}

/** Task batch started — set running state so the UI can react. */
function handleTaskStarted(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  handleCommon(event, stores)
  stores.indexStore.setTaskRunning(true)
}

/** Task batch completed — clear running state. */
function handleTaskCompleted(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  handleCommon(event, stores)
  stores.indexStore.setTaskRunning(false)
}

/** Task batch failed — clear running state. */
function handleTaskFailed(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  handleCommon(event, stores)
  stores.indexStore.setTaskRunning(false)
}

/**
 * Per-event-type handlers. Events not listed here fall through to
 * handleCommon (log + notify channels only).
 *
 * Only 7 of the 12 declared RealtimeEventName values are actually emitted
 * by the backend: log, focus.display, task.started, task.completed,
 * task.failed, notification.test. The other 6 (resource.loading,
 * controller.action, tasker.task, node.recognition, node.action, sink)
 * are dead code — all MAA sink callbacks funnel through "focus.display".
 */
const typeHandlers: Partial<
  Record<RealtimeEventName, (event: RealtimeEvent, stores: RealtimeStoreRefs) => void>
> = {
  "task.started": handleTaskStarted,
  "task.completed": handleTaskCompleted,
  "task.failed": handleTaskFailed,
}

/**
 * Unified SSE event dispatcher. Routes incoming RealtimeEvents by type,
 * applying common handling (log + notify channels) plus type-specific
 * side effects (e.g. task lifecycle → store state updates).
 */
export function dispatchRealtimeEvent(event: RealtimeEvent, stores: RealtimeStoreRefs): void {
  const handler = typeHandlers[event.event]
  if (handler) {
    handler(event, stores)
  } else {
    handleCommon(event, stores)
  }
}
