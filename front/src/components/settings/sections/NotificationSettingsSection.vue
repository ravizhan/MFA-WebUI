<template>
  <n-card
    id="notification-settings"
    class="mb-6 scroll-mt-5 last:mb-0"
    :title="t('settings.notification.title')"
  >
    <template #header-extra>
      <n-button
        size="small"
        type="info"
        @click="testNotification"
        :disabled="isTestNotificationDisabled"
      >
        {{ t("settings.notification.test") }}
      </n-button>
    </template>
    <n-form label-placement="left" label-width="120">
      <n-form-item :label="t('settings.notification.enable')">
        <n-space>
          <n-checkbox
            v-model:checked="settings.notification.systemNotification"
            @update:checked="
              (val: boolean) => handleSettingChange('notification', 'systemNotification', val)
            "
          >
            {{ t("settings.notification.system") }}
          </n-checkbox>
          <n-checkbox
            :checked="settings.notification.browserNotification"
            @update:checked="handleBrowserNotificationChange"
          >
            {{ t("settings.notification.browser") }}
          </n-checkbox>
          <n-checkbox
            v-model:checked="settings.notification.externalNotification"
            @update:checked="
              (val: boolean) => handleSettingChange('notification', 'externalNotification', val)
            "
          >
            {{ t("settings.notification.external") }}
          </n-checkbox>
        </n-space>
      </n-form-item>
    </n-form>
    <template v-if="settings.notification.externalNotification">
      <n-form label-placement="top">
        <n-form-item label="url *">
          <n-input
            v-model:value="settings.notification.webhook"
            placeholder="https://..."
            @update:value="(val: string) => handleSettingChange('notification', 'webhook', val)"
          />
        </n-form-item>
        <n-form-item label="content_type" v-if="settings.notification.method !== 'GET'">
          <n-select
            v-model:value="settings.notification.contentType"
            :options="contentTypeOptions"
            @update:value="
              (val: string) =>
                handleSettingChange(
                  'notification',
                  'contentType',
                  val as SettingsModel['notification']['contentType'],
                )
            "
          />
        </n-form-item>
        <n-form-item label="headers">
          <n-input
            v-model:value="settings.notification.headers"
            placeholder="HTTP headers in JSON format"
            @update:value="(val: string) => handleSettingChange('notification', 'headers', val)"
          />
        </n-form-item>
        <n-form-item label="body">
          <n-input
            v-model:value="settings.notification.body"
            type="textarea"
            placeholder='{"desp":"{{message}}","title":"{{title}}"}'
            :autosize="{ minRows: 2, maxRows: 5 }"
            @update:value="(val: string) => handleSettingChange('notification', 'body', val)"
          />
        </n-form-item>
        <n-form-item label="username">
          <n-input
            v-model:value="settings.notification.username"
            @update:value="(val: string) => handleSettingChange('notification', 'username', val)"
          />
        </n-form-item>
        <n-form-item label="password">
          <n-input
            v-model:value="settings.notification.password"
            type="password"
            show-password-on="click"
            @update:value="(val: string) => handleSettingChange('notification', 'password', val)"
          />
        </n-form-item>
        <n-form-item label="method">
          <n-select
            v-model:value="settings.notification.method"
            :options="methodOptions"
            @update:value="
              (val: string) =>
                handleSettingChange(
                  'notification',
                  'method',
                  val as SettingsModel['notification']['method'],
                )
            "
          />
        </n-form-item>
      </n-form>
    </template>
    <n-divider />
    <n-form label-placement="left" label-width="120">
      <n-form-item :label="t('settings.notification.onComplete')">
        <n-switch
          v-model:value="settings.notification.notifyOnComplete"
          @update:value="
            (val: boolean) => handleSettingChange('notification', 'notifyOnComplete', val)
          "
        />
      </n-form-item>
      <n-form-item :label="t('settings.notification.onError')">
        <n-switch
          v-model:value="settings.notification.notifyOnError"
          @update:value="
            (val: boolean) => handleSettingChange('notification', 'notifyOnError', val)
          "
        />
      </n-form-item>
    </n-form>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useMessage } from "naive-ui"
import { useI18n } from "vue-i18n"
import { testNotificationApi } from "@/services/api"
import { useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settings/model"

const { t } = useI18n()
const message = useMessage()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

const methodOptions = [
  { label: "POST", value: "POST" },
  { label: "GET", value: "GET" },
]

const contentTypeOptions = [
  { label: "application/json", value: "application/json" },
  { label: "application/x-www-form-urlencoded", value: "application/x-www-form-urlencoded" },
]

const isTestNotificationDisabled = computed(() => {
  const notification = settings.value.notification
  const hasEnabledChannel =
    notification.systemNotification ||
    notification.browserNotification ||
    notification.externalNotification

  if (!hasEnabledChannel) {
    return true
  }

  if (
    notification.externalNotification &&
    !notification.webhook &&
    !notification.systemNotification &&
    !notification.browserNotification
  ) {
    return true
  }

  return false
})

type EditableCategory = Exclude<keyof SettingsModel, "about">

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: SettingsModel[K][P],
) {
  await settingsStore.updateSetting(category, key, value)
}

async function handleBrowserNotificationChange(enabled: boolean) {
  if (!enabled) {
    await handleSettingChange("notification", "browserNotification", false)
    return
  }

  if (typeof Notification === "undefined") {
    message.error(t("settings.notification.browserUnsupported"))
    return
  }

  let permission = Notification.permission
  if (permission !== "granted") {
    permission = await Notification.requestPermission()
  }

  if (permission !== "granted") {
    message.warning(t("settings.notification.browserPermissionDenied"))
    return
  }

  await handleSettingChange("notification", "browserNotification", true)
}

async function testNotification() {
  message.info(t("settings.notification.testSending"))
  try {
    const result = await testNotificationApi()
    if (result.status !== "success") {
      message.error(t("settings.notification.testResult", { message: result.message }))
    }
  } catch (error) {
    message.error(t("settings.notification.testError"))
    console.error(error)
  }
}
</script>
