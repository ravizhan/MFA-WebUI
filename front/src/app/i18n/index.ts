import { createI18n } from "vue-i18n"
import zhCN from "@/app/i18n/messages/zh-CN.json"

type MessageSchema = typeof zhCN
type Locale = "zh-CN" | "en-US"

// Empty placeholder keeps the locale type union intact; real messages
// are loaded on demand.
const enUS: MessageSchema = JSON.parse("{}")

const DEFAULT_LOCALE = "zh-CN" as const

function isLocale(value: string | null): value is "zh-CN" | "en-US" {
  return value === "zh-CN" || value === "en-US"
}

const savedLocale = localStorage.getItem("locale")
const savedLang = localStorage.getItem("lang")
let locale: Locale = DEFAULT_LOCALE
if (isLocale(savedLocale)) {
  locale = savedLocale
}
if (!isLocale(savedLocale) && isLocale(savedLang)) {
  locale = savedLang
}

const i18n = createI18n<[MessageSchema], Locale>({
  legacy: false,
  globalInjection: true,
  locale: DEFAULT_LOCALE,
  fallbackLocale: DEFAULT_LOCALE,
  messages: {
    [DEFAULT_LOCALE]: zhCN,
    "en-US": enUS,
  },
})

/**
 * Lazily loads a locale and activates it. The default locale is bundled;
 * other locales are fetched on demand as separate chunks. Static imports
 * cannot be used here because the target locale is runtime-selected.
 */
export async function loadLocale(target: Locale) {
  if (i18n.global.availableLocales.includes(target)) {
    applyLocale(target)
    return
  }
  const messages = await import(`@/app/i18n/messages/${target}.json`)
  i18n.global.setLocaleMessage(target, messages.default)
  applyLocale(target)
}

// Runtime-verified: createI18n always returns a WritableComputedRef for
// `global.locale` in composition mode, but the type union doesn't reflect
// that for generic Locale parameters.
function applyLocale(target: Locale) {
  const loc: unknown = i18n.global.locale
  if (typeof loc === "object" && loc !== null && "value" in loc) {
    Object.assign(loc, { value: target })
  }
}

if (locale !== DEFAULT_LOCALE) {
  void loadLocale(locale)
}

export default i18n
