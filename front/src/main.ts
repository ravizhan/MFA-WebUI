import "./assets/main.css"
import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"
import { createPinia } from "pinia"
import { useIndexStore } from "./stores"
import { useSettingsStore } from "./stores/settings"
import { sse } from "./services/sse"
import {
  formatRealtimeLog,
  showBrowserRealtimeNotification,
  showRealtimeMessage,
} from "./services/realtime"
import type { RealtimeEvent } from "./types/realtime"
import "virtual:uno.css"
import i18n from "./locales/i18n"

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
