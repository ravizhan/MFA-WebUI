import { createI18n } from "vue-i18n"
import zhCN from "../locales/zh-CN.json"
import enUS from "../locales/en-US.json"

type MessageSchema = typeof zhCN

const i18n = createI18n<[MessageSchema], "zh-CN" | "en-US">({
  legacy: false,
  globalInjection: true,
  locale: (localStorage.getItem("lang") as "zh-CN" | "en-US") || "zh-CN",
  fallbackLocale: "zh-CN",
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
})

export default i18n
