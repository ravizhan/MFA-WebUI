import "@/app.css"
import "@/app/styles/main.css"
import { createApp } from "vue"
import { createPinia } from "pinia"
import App from "@/app/App.vue"
import router from "@/app/router"
import i18n from "@/app/i18n"
import { useIndexStore, useSettingsStore } from "@/stores"
import { sse } from "@/services/realtime/sse"
import { dispatchRealtimeEvent } from "@/services/realtime/dispatcher"
import type { RealtimeEventName } from "@/types/realtimeModel"

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(i18n)

const indexStore = useIndexStore(pinia)
const settingsStore = useSettingsStore(pinia)

const stores = { indexStore, settingsStore }

/**
 * All SSE event types. The dispatcher routes each event by type,
 * applying common handling (log + notify channels) plus type-specific
 * side effects (e.g. task lifecycle → store state updates).
 */
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
).forEach((eventName: RealtimeEventName) => {
  sse.addEventListener(eventName, (event) => dispatchRealtimeEvent(event, stores))
})

app.mount("#app")
