<template>
  <div class="space-y-0">
    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.ui.language") }}
      </label>
      <select
        :value="locale"
        class="select select-bordered w-full md:w-auto"
        @change="handleLocaleChange(($event.target as HTMLSelectElement).value)"
      >
        <option value="zh-CN">{{ t("settings.ui.languages.zhCN") }}</option>
        <option value="en-US">{{ t("settings.ui.languages.enUS") }}</option>
      </select>
    </div>

    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.ui.darkMode") }}
      </label>
      <select
        :value="String(settings.ui.darkMode)"
        class="select select-bordered w-full md:w-auto"
        @change="handleDarkModeChange(($event.target as HTMLSelectElement).value)"
      >
        <option value="auto">{{ t("settings.ui.darkModeOptions.auto") }}</option>
        <option value="false">{{ t("settings.ui.darkModeOptions.off") }}</option>
        <option value="true">{{ t("settings.ui.darkModeOptions.on") }}</option>
      </select>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settingsModel"

const { t, locale } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

type EditableCategory = Exclude<keyof SettingsModel, "about">

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: SettingsModel[K][P],
) {
  await settingsStore.updateSetting(category, key, value)
}

function handleLocaleChange(val: string) {
  locale.value = val
  localStorage.setItem("locale", val)
  window.location.reload()
}

function handleDarkModeChange(val: string) {
  if (val === "auto") {
    void handleSettingChange("ui", "darkMode", "auto")
    return
  }
  if (val === "true") {
    void handleSettingChange("ui", "darkMode", true)
    return
  }
  void handleSettingChange("ui", "darkMode", false)
}
</script>
