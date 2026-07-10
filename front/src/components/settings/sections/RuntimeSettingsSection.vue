<template>
  <div class="space-y-0">
    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.runtime.timeout") }}
      </label>
      <div class="flex items-center gap-2">
        <input
          :value="settings.runtime.timeout"
          type="number"
          class="input input-bordered w-32"
          min="60"
          max="3600"
          step="30"
          @change="handleNumberChange('timeout', $event, 60, 3600)"
        />
        <span class="text-sm opacity-60">{{ t("settings.runtime.timeoutSuffix") }}</span>
      </div>
    </div>

    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.runtime.reminderInterval") }}
      </label>
      <div class="flex items-center gap-2">
        <input
          :value="settings.runtime.reminderInterval"
          type="number"
          class="input input-bordered w-32"
          min="5"
          max="120"
          step="5"
          @change="handleNumberChange('reminderInterval', $event, 5, 120)"
        />
        <span class="text-sm opacity-60">{{ t("settings.runtime.reminderSuffix") }}</span>
      </div>
    </div>

    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.runtime.autoRetry") }}
      </label>
      <div class="flex items-center">
        <input
          type="checkbox"
          class="toggle toggle-primary"
          :checked="settings.runtime.autoRetry"
          @change="
            handleSettingChange('runtime', 'autoRetry', ($event.target as HTMLInputElement).checked)
          "
        />
      </div>
    </div>

    <div
      v-if="settings.runtime.autoRetry"
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.runtime.maxRetryCount") }}
      </label>
      <input
        :value="settings.runtime.maxRetryCount"
        type="number"
        class="input input-bordered w-32"
        min="1"
        max="10"
        @change="handleNumberChange('maxRetryCount', $event, 1, 10)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settingsModel"

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

type EditableCategory = Exclude<keyof SettingsModel, "about">
type MaybeNullForNumbers<T> = T extends number ? T | null : T
type EditableSettingValue<
  K extends EditableCategory,
  P extends keyof SettingsModel[K],
> = MaybeNullForNumbers<SettingsModel[K][P]>

type RuntimeNumberKey = "timeout" | "reminderInterval" | "maxRetryCount"

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: EditableSettingValue<K, P>,
) {
  if (value === null) return
  if (typeof value === "number" && Number.isNaN(value)) return
  await settingsStore.updateSetting(category, key, value)
}

async function handleNumberChange(key: RuntimeNumberKey, event: Event, min: number, max: number) {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return

  const raw = target.value
  if (raw === "" || raw.trim() === "") return

  const num = Number(raw)
  if (Number.isNaN(num)) return

  const clamped = Math.min(max, Math.max(min, num))
  // Keep controlled input in sync if browser allowed out-of-range value
  if (clamped !== num) {
    target.value = String(clamped)
  }
  await handleSettingChange("runtime", key, clamped)
}
</script>
