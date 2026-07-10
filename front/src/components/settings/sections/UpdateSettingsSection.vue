<template>
  <div class="space-y-0">
    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.auto") }}
      </label>
      <div class="flex items-center justify-between">
        <input
          type="checkbox"
          class="toggle toggle-primary"
          :checked="settings.update.autoUpdate"
          @change="
            handleSettingChange('update', 'autoUpdate', ($event.target as HTMLInputElement).checked)
          "
        />
        <button class="btn btn-primary btn-sm" :disabled="checkingUpdate" @click="checkForUpdate">
          <Icon v-if="checkingUpdate" icon="mdi:loading" class="animate-spin mr-1 text-base" />
          <Icon v-else icon="mdi:update" class="mr-1 text-base" />
          {{ t("settings.update.check") }}
        </button>
      </div>
    </div>

    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.channel") }}
      </label>
      <select
        :value="settings.update.updateChannel"
        class="select select-bordered w-full md:w-auto"
        @change="handleUpdateChannelChange($event)"
      >
        <option value="stable">{{ t("settings.update.channelOptions.stable") }}</option>
        <option value="beta">{{ t("settings.update.channelOptions.beta") }}</option>
      </select>
    </div>

    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.proxy") }}
      </label>
      <input
        :value="settings.update.proxy"
        type="text"
        class="input input-bordered w-full"
        placeholder="http://127.0.0.1:7890"
        @input="handleSettingChange('update', 'proxy', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div
      v-if="interfaceStore.interface?.mirrorchyan_rid"
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.mirrorchyanCdk") }}
      </label>
      <div class="flex gap-2">
        <input
          :value="settings.update.mirrorchyanCdk"
          type="password"
          class="input input-bordered flex-1"
          :placeholder="t('settings.update.mirrorchyanCdkPlaceholder')"
          @input="
            handleSettingChange(
              'update',
              'mirrorchyanCdk',
              ($event.target as HTMLInputElement).value,
            )
          "
        />
        <a href="https://mirrorchyan.com" target="_blank" class="btn btn-outline">
          {{ t("settings.update.mirrorchyanCdkHint") }}
        </a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { checkUpdateApi, type UpdateInfo } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore, useSettingsStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import type { SettingsModel } from "@/types/settingsModel"

const emit = defineEmits<{
  (e: "show-update", updateInfo: UpdateInfo): void
}>()

function isUpdateChannel(value: string): value is SettingsModel["update"]["updateChannel"] {
  return value === "stable" || value === "beta"
}

const { t } = useI18n()
const settingsStore = useSettingsStore()
const interfaceStore = useInterfaceStore()
const settings = computed(() => settingsStore.settings)
const checkingUpdate = ref(false)

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
  await settingsStore.updateSetting(category, key, value)
}

function handleUpdateChannelChange(event: Event) {
  const target = event.target
  if (!(target instanceof HTMLSelectElement)) return
  const value = target.value
  if (!isUpdateChannel(value)) return
  void handleSettingChange("update", "updateChannel", value)
}

async function checkForUpdate() {
  checkingUpdate.value = true
  const [result, err] = await tryCatch(() => checkUpdateApi())
  if (err) {
    showGlobalMessage("error", t("settings.update.failed"))
    checkingUpdate.value = false
    return
  }

  if (result.status === "success" && result.update_info?.is_update_available) {
    emit("show-update", result.update_info)
    checkingUpdate.value = false
    return
  }
  showGlobalMessage("success", t("settings.update.latest"))
  checkingUpdate.value = false
}
</script>
