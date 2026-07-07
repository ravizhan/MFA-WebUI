<template>
  <div class="space-y-0">
    <div class="flex justify-end pb-4">
      <button class="btn btn-primary btn-sm" :disabled="checkingUpdate" @click="checkForUpdate">
        <Icon v-if="checkingUpdate" icon="mdi:loading" class="animate-spin mr-1 text-base" />
        <Icon v-else icon="mdi:update" class="mr-1 text-base" />
        {{ t("settings.update.check") }}
      </button>
    </div>

    <div class="border-t border-base-200" />

    <div
      class="grid grid-cols-1 md:grid-cols-[140px_1fr] gap-2 md:gap-4 items-center py-4 border-b border-base-200 last:border-b-0"
    >
      <label class="text-sm font-medium md:text-right">
        {{ t("settings.update.auto") }}
      </label>
      <div class="flex items-center">
        <input
          type="checkbox"
          class="toggle toggle-primary"
          :checked="settings.update.autoUpdate"
          @change="
            handleSettingChange('update', 'autoUpdate', ($event.target as HTMLInputElement).checked)
          "
        />
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
        @change="
          handleSettingChange(
            'update',
            'updateChannel',
            ($event.target as HTMLSelectElement).value as SettingsModel['update']['updateChannel'],
          )
        "
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
import type { SettingsModel } from "@/types/settings/model"

const emit = defineEmits<{
  (e: "show-update", updateInfo: UpdateInfo): void
}>()

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
  await settingsStore.updateSetting(category, key, value as SettingsModel[K][P])
}

async function checkForUpdate() {
  checkingUpdate.value = true
  try {
    const result = await checkUpdateApi()
    if (result.status === "success" && result.update_info?.is_update_available) {
      emit("show-update", result.update_info)
    } else {
      showGlobalMessage("success", t("settings.update.latest"))
    }
  } catch {
    showGlobalMessage("error", t("settings.update.failed"))
  } finally {
    checkingUpdate.value = false
  }
}
</script>
