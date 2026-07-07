import "@/app.css"
import { createApp } from "vue"
import { createPinia } from "pinia"
import App from "@/app/App.vue"
import router from "@/app/router"
import i18n from "@/app/i18n"
import { useIndexStore, useSettingsStore } from "@/stores"
import { sse } from "@/services/realtime/sse"
import {
  formatRealtimeLog,
  showBrowserRealtimeNotification,
  showRealtimeMessage,
  showToastMessage,
} from "@/services/realtime/events"
import type { RealtimeEvent } from "@/types/realtime/model"

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(i18n)

const indexStore = useIndexStore(pinia)
const settingsStore = useSettingsStore(pinia)

function handleRealtimeEvent(data: RealtimeEvent): void {
  if (data.display) {
    indexStore.UpdateLog(formatRealtimeLog(data))
  }
  if (data.notify.includes("toast")) {
    showToastMessage(data)
  }
  if (data.notify.includes("notification")) {
    showBrowserRealtimeNotification(data, settingsStore.settings.notification)
  }

  if (data.notify.length === 0) {
    return
  }

  showRealtimeMessage(data)
}

/** 所有 SSE 事件类型（保持兼容：非 sink 事件仍独立触发 handleRealtimeEvent） */
;(
  [
    "log",
    "focus.display",
    "task.started",
    "task.completed",
    "task.failed",
    "notification.test",
    "resource.loading",
    "controller.action",
    "tasker.task",
    "node.recognition",
    "node.action",
    "sink",
  ] as const
).forEach((eventName) => {
  sse.addEventListener(eventName, handleRealtimeEvent)
})

app.mount("#app")
