import { createI18n } from "vue-i18n"
import enUS from "@/app/i18n/messages/en-US.json"
import zhCN from "@/app/i18n/messages/zh-CN.json"

type MessageSchema = typeof zhCN
type Locale = "zh-CN" | "en-US"

const DEFAULT_LOCALE = "zh-CN" as const

const savedLocale = localStorage.getItem("locale")
const savedLang = localStorage.getItem("lang")
let locale: Locale = DEFAULT_LOCALE
if (savedLocale === "zh-CN" || savedLocale === "en-US") {
  locale = savedLocale
}
if (
  !(savedLocale === "zh-CN" || savedLocale === "en-US") &&
  (savedLang === "zh-CN" || savedLang === "en-US")
) {
  locale = savedLang
}

const i18n = createI18n<[MessageSchema], Locale>({
  legacy: false,
  globalInjection: true,
  locale,
  fallbackLocale: DEFAULT_LOCALE,
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
})

export default i18n
