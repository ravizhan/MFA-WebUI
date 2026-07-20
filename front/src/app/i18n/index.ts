import { createI18n } from "vue-i18n"
import zhCN from "@/app/i18n/messages/zh-CN.json"
import enUS from "@/app/i18n/messages/en-US.json"

type MessageSchema = typeof zhCN

function isLocale(value: string | null): value is "zh-CN" | "en-US" {
  return value === "zh-CN" || value === "en-US"
}

const savedLocale = localStorage.getItem("locale")
let locale: "zh-CN" | "en-US" = "zh-CN"
if (isLocale(savedLocale)) {
  locale = savedLocale
}

const i18n = createI18n<[MessageSchema], "zh-CN" | "en-US">({
  legacy: false,
  globalInjection: true,
  locale,
  fallbackLocale: "zh-CN",
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
})

export default i18n
