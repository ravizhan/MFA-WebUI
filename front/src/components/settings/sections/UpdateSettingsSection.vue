<template>
  <n-card
    id="update-settings"
    class="mb-6 scroll-mt-5 last:mb-0"
    :title="t('settings.update.title')"
  >
    <template #header-extra>
      <n-button size="small" type="primary" @click="checkForUpdate" :loading="checkingUpdate">
        {{ t("settings.update.check") }}
      </n-button>
    </template>
    <n-form label-placement="left" label-width="120">
      <n-form-item :label="t('settings.update.auto')">
        <n-switch
          v-model:value="settings.update.autoUpdate"
          @update:value="(val: boolean) => handleSettingChange('update', 'autoUpdate', val)"
        />
      </n-form-item>
      <n-form-item :label="t('settings.update.channel')">
        <n-select
          v-model:value="settings.update.updateChannel"
          :options="updateChannelOptions"
          @update:value="
            (val: string) =>
              handleSettingChange(
                'update',
                'updateChannel',
                val as SettingsModel['update']['updateChannel'],
              )
          "
        />
      </n-form-item>
      <n-form-item :label="t('settings.update.proxy')">
        <n-input
          v-model:value="settings.update.proxy"
          placeholder="http://127.0.0.1:7890"
          clearable
          @update:value="(val: string) => handleSettingChange('update', 'proxy', val)"
        />
      </n-form-item>
      <n-form-item
        v-if="interfaceStore.interface?.mirrorchyan_rid"
        :label="t('settings.update.mirrorchyanCdk')"
      >
        <n-input-group>
          <n-input
            v-model:value="settings.update.mirrorchyanCdk"
            type="password"
            show-password-on="click"
            :placeholder="t('settings.update.mirrorchyanCdkPlaceholder')"
            clearable
            @update:value="(val: string) => handleSettingChange('update', 'mirrorchyanCdk', val)"
          />
          <n-button tag="a" href="https://mirrorchyan.com" target="_blank" type="primary" ghost>
            {{ t("settings.update.mirrorchyanCdkHint") }}
          </n-button>
        </n-input-group>
      </n-form-item>
    </n-form>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { useMessage } from "naive-ui"
import { useI18n } from "vue-i18n"
import { checkUpdateApi, type UpdateInfo } from "@/services/api"
import { useInterfaceStore, useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settings/model"

const emit = defineEmits<{
  (e: "show-update", updateInfo: UpdateInfo): void
}>()

const message = useMessage()
const { t } = useI18n()
const settingsStore = useSettingsStore()
const interfaceStore = useInterfaceStore()
const settings = computed(() => settingsStore.settings)
const checkingUpdate = ref(false)

const updateChannelOptions = computed(() => [
  { label: t("settings.update.channelOptions.stable"), value: "stable" },
  { label: t("settings.update.channelOptions.beta"), value: "beta" },
])

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
      message.success(t("settings.update.latest"))
    }
  } catch {
    message.error(t("settings.update.failed"))
  } finally {
    checkingUpdate.value = false
  }
}
</script>
