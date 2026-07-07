<template>
  <div class="space-y-4">
    <div class="flex justify-end">
      <button
        class="btn btn-info btn-sm"
        :disabled="isTestNotificationDisabled"
        @click="testNotification"
      >
        <Icon icon="mdi:bell-ring" class="mr-1 text-base" />
        {{ t("settings.notification.test") }}
      </button>
    </div>

    <div class="form-control">
      <label class="label">
        <span class="label-text">{{ t("settings.notification.enable") }}</span>
      </label>
      <div class="flex flex-wrap gap-4">
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            class="checkbox checkbox-primary"
            :checked="settings.notification.systemNotification"
            @change="
              handleSettingChange(
                'notification',
                'systemNotification',
                ($event.target as HTMLInputElement).checked,
              )
            "
          />
          <span class="text-sm">{{ t("settings.notification.system") }}</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            class="checkbox checkbox-primary"
            :checked="settings.notification.browserNotification"
            @change="handleBrowserNotificationChange(($event.target as HTMLInputElement).checked)"
          />
          <span class="text-sm">{{ t("settings.notification.browser") }}</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            class="checkbox checkbox-primary"
            :checked="settings.notification.externalNotification"
            @change="
              handleSettingChange(
                'notification',
                'externalNotification',
                ($event.target as HTMLInputElement).checked,
              )
            "
          />
          <span class="text-sm">{{ t("settings.notification.external") }}</span>
        </label>
      </div>
    </div>

    <template v-if="settings.notification.externalNotification">
      <div class="divider" />
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="form-control">
          <label class="label"><span class="label-text">url *</span></label>
          <input
            :value="settings.notification.webhook"
            type="text"
            class="input input-bordered"
            placeholder="https://..."
            @input="
              handleSettingChange(
                'notification',
                'webhook',
                ($event.target as HTMLInputElement).value,
              )
            "
          />
        </div>
        <div v-if="settings.notification.method !== 'GET'" class="form-control">
          <label class="label"><span class="label-text">content_type</span></label>
          <select
            :value="settings.notification.contentType"
            class="select select-bordered"
            @change="
              handleSettingChange(
                'notification',
                'contentType',
                ($event.target as HTMLSelectElement)
                  .value as SettingsModel['notification']['contentType'],
              )
            "
          >
            <option value="application/json">application/json</option>
            <option value="application/x-www-form-urlencoded">
              application/x-www-form-urlencoded
            </option>
          </select>
        </div>
        <div class="form-control">
          <label class="label"><span class="label-text">headers</span></label>
          <input
            :value="settings.notification.headers"
            type="text"
            class="input input-bordered"
            placeholder="HTTP headers in JSON format"
            @input="
              handleSettingChange(
                'notification',
                'headers',
                ($event.target as HTMLInputElement).value,
              )
            "
          />
        </div>
        <div class="form-control">
          <label class="label"><span class="label-text">method</span></label>
          <select
            :value="settings.notification.method"
            class="select select-bordered"
            @change="
              handleSettingChange(
                'notification',
                'method',
                ($event.target as HTMLSelectElement)
                  .value as SettingsModel['notification']['method'],
              )
            "
          >
            <option value="POST">POST</option>
            <option value="GET">GET</option>
          </select>
        </div>
        <div class="form-control md:col-span-2">
          <label class="label"><span class="label-text">body</span></label>
          <textarea
            :value="settings.notification.body"
            class="textarea textarea-bordered"
            placeholder='{"desp":"{{message}}","title":"{{title}}"}'
            rows="3"
            @input="
              handleSettingChange(
                'notification',
                'body',
                ($event.target as HTMLTextAreaElement).value,
              )
            "
          />
        </div>
        <div class="form-control">
          <label class="label"><span class="label-text">username</span></label>
          <input
            :value="settings.notification.username"
            type="text"
            class="input input-bordered"
            @input="
              handleSettingChange(
                'notification',
                'username',
                ($event.target as HTMLInputElement).value,
              )
            "
          />
        </div>
        <div class="form-control">
          <label class="label"><span class="label-text">password</span></label>
          <input
            :value="settings.notification.password"
            type="password"
            class="input input-bordered"
            @input="
              handleSettingChange(
                'notification',
                'password',
                ($event.target as HTMLInputElement).value,
              )
            "
          />
        </div>
      </div>
    </template>

    <div class="divider" />

    <div class="form-control">
      <label class="label cursor-pointer">
        <span class="label-text">{{ t("settings.notification.onComplete") }}</span>
        <input
          type="checkbox"
          class="toggle toggle-primary"
          :checked="settings.notification.notifyOnComplete"
          @change="
            handleSettingChange(
              'notification',
              'notifyOnComplete',
              ($event.target as HTMLInputElement).checked,
            )
          "
        />
      </label>
    </div>
    <div class="form-control">
      <label class="label cursor-pointer">
        <span class="label-text">{{ t("settings.notification.onError") }}</span>
        <input
          type="checkbox"
          class="toggle toggle-primary"
          :checked="settings.notification.notifyOnError"
          @change="
            handleSettingChange(
              'notification',
              'notifyOnError',
              ($event.target as HTMLInputElement).checked,
            )
          "
        />
      </label>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { testNotificationApi } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useSettingsStore } from "@/stores"
import type { SettingsModel } from "@/types/settings/model"

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

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
    showGlobalMessage("error", t("settings.notification.browserUnsupported"))
    return
  }

  let permission = Notification.permission
  if (permission !== "granted") {
    permission = await Notification.requestPermission()
  }

  if (permission !== "granted") {
    showGlobalMessage("warning", t("settings.notification.browserPermissionDenied"))
    return
  }

  await handleSettingChange("notification", "browserNotification", true)
}

async function testNotification() {
  showGlobalMessage("info", t("settings.notification.testSending"))
  try {
    const result = await testNotificationApi()
    if (result.status !== "success") {
      showGlobalMessage("error", t("settings.notification.testResult", { message: result.message }))
    }
  } catch (error) {
    showGlobalMessage("error", t("settings.notification.testError"))
    console.error(error)
  }
}
</script>
