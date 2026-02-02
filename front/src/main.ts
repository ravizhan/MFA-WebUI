import "./assets/main.css"
import { createApp } from "vue"
import App from "./App.vue"
import router from "./router"
import { createPinia } from "pinia"
import "virtual:uno.css"
import i18n from "./libs/i18n"

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(i18n)
app.mount("#app")
