<template>
  <n-card
    id="runtime-settings"
    class="mb-6 scroll-mt-5 last:mb-0"
    :title="t('settings.runtime.title')"
  >
    <n-form label-placement="left" label-width="120">
      <n-form-item :label="t('settings.runtime.timeout')">
        <n-input-number
          v-model:value="settings.runtime.timeout"
          :min="60"
          :max="3600"
          :step="30"
          @update:value="(val: number | null) => handleSettingChange('runtime', 'timeout', val)"
        >
          <template #suffix>{{ t("settings.runtime.timeoutSuffix") }}</template>
        </n-input-number>
      </n-form-item>
      <n-form-item :label="t('settings.runtime.reminderInterval')">
        <n-input-number
          v-model:value="settings.runtime.reminderInterval"
          :min="5"
          :max="120"
          :step="5"
          @update:value="
            (val: number | null) => handleSettingChange('runtime', 'reminderInterval', val)
          "
        >
          <template #suffix>{{ t("settings.runtime.reminderSuffix") }}</template>
        </n-input-number>
      </n-form-item>
      <n-form-item :label="t('settings.runtime.autoRetry')">
        <n-switch
          v-model:value="settings.runtime.autoRetry"
          @update:value="(val: boolean) => handleSettingChange('runtime', 'autoRetry', val)"
        />
      </n-form-item>
      <n-form-item :label="t('settings.runtime.maxRetryCount')" v-if="settings.runtime.autoRetry">
        <n-input-number
          v-model:value="settings.runtime.maxRetryCount"
          :min="1"
          :max="10"
          @update:value="
            (val: number | null) => handleSettingChange('runtime', 'maxRetryCount', val)
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

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

type EditableCategory = Exclude<keyof SettingsModel, "about">
type MaybeNullForNumbers<T> = T extends number ? T | null : T
type EditableSettingValue<
  K extends EditableCategory,
  P extends keyof SettingsModel[K],
> = MaybeNullForNumbers<SettingsModel[K][P]>

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: EditableSettingValue<K, P>,
) {
  if (value === null) return
  await settingsStore.updateSetting(category, key, value as SettingsModel[K][P])
}
</script>
