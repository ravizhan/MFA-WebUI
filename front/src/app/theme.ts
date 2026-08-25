import { computed } from "vue"
import { darkTheme, zhCN, enUS, dateZhCN, dateEnUS } from "naive-ui"
import type { GlobalThemeOverrides } from "naive-ui"
import { useI18n } from "vue-i18n"
import { useSettingsStore } from "@/stores"

const CARD_SHADOW = "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)"

const lightOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#009036",
    primaryColorHover: "#00a53e",
    primaryColorPressed: "#007a2c",
    primaryColorSuppl: "#009036",
    successColor: "#00af44",
    infoColor: "#26a9f1",
    warningColor: "#f2b200",
    errorColor: "#e62b34",
    bodyColor: "#edf4ef",
    cardColor: "#f9fdfa",
    modalColor: "#f9fdfa",
    popoverColor: "#f9fdfa",
    textColorBase: "#0a1a10",
    borderRadius: "8px",
    borderRadiusSmall: "4px",
  },
  Card: {
    boxShadow: CARD_SHADOW,
    borderRadius: "8px",
  },
}

const darkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#00b054",
    primaryColorHover: "#22c168",
    primaryColorPressed: "#009a48",
    primaryColorSuppl: "#00b054",
    successColor: "#00af44",
    infoColor: "#26a9f1",
    warningColor: "#e1a200",
    errorColor: "#f94144",
    bodyColor: "#0f1912",
    cardColor: "#061009",
    modalColor: "#061009",
    popoverColor: "#061009",
    textColorBase: "#d4e2d8",
    borderRadius: "8px",
    borderRadiusSmall: "4px",
  },
  Card: {
    boxShadow: CARD_SHADOW,
    borderRadius: "8px",
  },
}

export function useNaiveTheme() {
  const settingsStore = useSettingsStore()
  const { locale: i18nLocale } = useI18n()

  const theme = computed(() => (settingsStore.isDarkMode ? darkTheme : null))
  const themeOverrides = computed(() => (settingsStore.isDarkMode ? darkOverrides : lightOverrides))
  const locale = computed(() => (i18nLocale.value.startsWith("zh") ? zhCN : enUS))
  const dateLocale = computed(() => (i18nLocale.value.startsWith("zh") ? dateZhCN : dateEnUS))

  return { theme, themeOverrides, locale, dateLocale }
}
