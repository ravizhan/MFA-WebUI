import "@/app/styles/main.css"
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
} from "@/services/realtime/events"
import type { RealtimeEvent } from "@/types/realtime/model"
import "virtual:uno.css"

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(i18n)

const indexStore = useIndexStore(pinia)
const settingsStore = useSettingsStore(pinia)

function handleRealtimeEvent(data: RealtimeEvent): void {
  indexStore.UpdateLog(formatRealtimeLog(data))

  if (!data.notify) {
    return
  }

  showRealtimeMessage(data)
  showBrowserRealtimeNotification(data, settingsStore.settings.notification)
}

;(["log", "task.started", "task.completed", "task.failed", "notification.test"] as const).forEach(
  (eventName) => {
    sse.addEventListener(eventName, handleRealtimeEvent)
  },
)

app.mount("#app")
