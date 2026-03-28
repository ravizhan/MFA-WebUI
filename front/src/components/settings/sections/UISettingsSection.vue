<template>
  <n-card id="ui-settings" class="mb-6 scroll-mt-5 last:mb-0" :title="t('settings.ui.title')">
    <n-form label-placement="left" label-width="120">
      <n-form-item :label="t('settings.ui.language')">
        <n-select :value="locale" :options="localeOptions" @update:value="handleLocaleChange" />
      </n-form-item>
      <n-form-item :label="t('settings.ui.darkMode')">
        <n-select
          v-model:value="settings.ui.darkMode"
          :options="darkModeOptions"
          @update:value="
            (val: string | boolean) =>
              (val === 'auto' || typeof val === 'boolean') &&
              handleSettingChange('ui', 'darkMode', val as SettingsModel['ui']['darkMode'])
          "
        />
      </n-form-item>
    </n-form>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settings/model"

const { t, locale } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

const localeOptions = [
  { label: "简体中文", value: "zh-CN" },
  { label: "English", value: "en-US" },
]

const darkModeOptions = computed(() => [
  { label: t("settings.ui.darkModeOptions.auto"), value: "auto" },
  { label: t("settings.ui.darkModeOptions.off"), value: false },
  { label: t("settings.ui.darkModeOptions.on"), value: true },
])

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
}
</script>
