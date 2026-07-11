<template>
  <div class="space-y-6">
    <!-- Channels + test -->
    <section class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex min-w-0 items-center gap-2">
          <Icon icon="mdi:bell-outline" class="text-primary shrink-0 text-lg" aria-hidden="true" />
          <h3 class="text-sm font-semibold">{{ t("settings.notification.sections.channels") }}</h3>
        </div>
        <button
          type="button"
          class="btn btn-primary btn-sm"
          :disabled="isTestNotificationDisabled"
          :title="t('settings.notification.test')"
          :aria-label="t('settings.notification.test')"
          @click="testNotification"
        >
          <Icon icon="mdi:bell-ring" class="text-base" aria-hidden="true" />
          {{ t("settings.notification.test") }}
        </button>
      </div>

      <div class="flex flex-wrap gap-2">
        <label
          class="border-base-300 hover:border-primary/40 has-[:checked]:border-primary has-[:checked]:bg-primary/5 flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 transition-colors"
        >
          <input
            type="checkbox"
            class="checkbox checkbox-primary checkbox-sm"
            :checked="settings.notification.systemNotification"
            @change="
              handleSettingChange('notification', 'systemNotification', getCheckboxValue($event))
            "
          />
          <Icon icon="mdi:desktop-mac" class="text-base opacity-70" aria-hidden="true" />
          <span class="text-sm">{{ t("settings.notification.system") }}</span>
        </label>

        <label
          class="border-base-300 hover:border-primary/40 has-[:checked]:border-primary has-[:checked]:bg-primary/5 flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 transition-colors"
        >
          <input
            type="checkbox"
            class="checkbox checkbox-primary checkbox-sm"
            :checked="settings.notification.browserNotification"
            @change="handleBrowserNotificationChange(getCheckboxValue($event))"
          />
          <Icon icon="mdi:web" class="text-base opacity-70" aria-hidden="true" />
          <span class="text-sm">{{ t("settings.notification.browser") }}</span>
        </label>

        <label
          class="border-base-300 hover:border-primary/40 has-[:checked]:border-primary has-[:checked]:bg-primary/5 flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 transition-colors"
        >
          <input
            type="checkbox"
            class="checkbox checkbox-primary checkbox-sm"
            :checked="settings.notification.externalNotification"
            @change="
              handleSettingChange('notification', 'externalNotification', getCheckboxValue($event))
            "
          />
          <Icon icon="mdi:webhook" class="text-base opacity-70" aria-hidden="true" />
          <span class="text-sm">{{ t("settings.notification.external") }}</span>
        </label>
      </div>
    </section>

    <!-- External connection (collapses when off) -->
    <section
      v-if="settings.notification.externalNotification"
      class="border-base-200 space-y-4 border-t pt-5"
    >
      <div class="flex items-center gap-2">
        <Icon icon="mdi:link-variant" class="text-primary shrink-0 text-lg" aria-hidden="true" />
        <h3 class="text-sm font-semibold">
          {{ t("settings.notification.sections.external") }}
        </h3>
      </div>

      <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
        <fieldset class="fieldset p-0 md:col-span-2">
          <legend class="fieldset-legend">{{ t("settings.notification.fields.url") }}</legend>
          <input
            :value="settings.notification.webhook"
            type="url"
            class="input input-bordered w-full font-mono text-sm"
            placeholder="https://..."
            autocomplete="off"
            spellcheck="false"
            @input="handleSettingChange('notification', 'webhook', getInputValue($event))"
          />
        </fieldset>

        <fieldset class="fieldset p-0">
          <legend class="fieldset-legend">{{ t("settings.notification.fields.method") }}</legend>
          <select
            :value="settings.notification.method"
            class="select select-bordered w-full"
            @change="handleMethodChange($event)"
          >
            <option value="POST">{{ t("settings.notification.fields.post") }}</option>
            <option value="GET">{{ t("settings.notification.fields.get") }}</option>
          </select>
        </fieldset>

        <fieldset v-if="settings.notification.method !== 'GET'" class="fieldset p-0">
          <legend class="fieldset-legend">
            {{ t("settings.notification.fields.contentType") }}
          </legend>
          <select
            :value="settings.notification.contentType"
            class="select select-bordered w-full"
            @change="handleContentTypeChange($event)"
          >
            <option value="application/json">{{ t("settings.notification.fields.json") }}</option>
            <option value="application/x-www-form-urlencoded">
              {{ t("settings.notification.fields.formUrlencoded") }}
            </option>
          </select>
        </fieldset>

        <fieldset class="fieldset p-0 md:col-span-2">
          <legend class="fieldset-legend">{{ t("settings.notification.fields.headers") }}</legend>
          <input
            :value="settings.notification.headers"
            type="text"
            class="input input-bordered w-full font-mono text-sm"
            placeholder='{"Authorization":"Bearer ..."}'
            autocomplete="off"
            spellcheck="false"
            @input="handleSettingChange('notification', 'headers', getInputValue($event))"
          />
        </fieldset>

        <fieldset class="fieldset p-0 md:col-span-2">
          <legend class="fieldset-legend">{{ t("settings.notification.fields.body") }}</legend>
          <textarea
            :value="settings.notification.body"
            class="textarea textarea-bordered min-h-24 w-full font-mono text-sm"
            placeholder='{"desp":"{{message}}","title":"{{title}}"}'
            rows="4"
            spellcheck="false"
            @input="handleSettingChange('notification', 'body', getTextareaValue($event))"
          />
        </fieldset>

        <fieldset class="fieldset p-0">
          <legend class="fieldset-legend">{{ t("settings.notification.fields.username") }}</legend>
          <input
            :value="settings.notification.username"
            type="text"
            class="input input-bordered w-full"
            autocomplete="username"
            @input="handleSettingChange('notification', 'username', getInputValue($event))"
          />
        </fieldset>

        <fieldset class="fieldset p-0">
          <legend class="fieldset-legend">{{ t("settings.notification.fields.password") }}</legend>
          <input
            :value="settings.notification.password"
            type="password"
            class="input input-bordered w-full"
            autocomplete="current-password"
            @input="handleSettingChange('notification', 'password', getInputValue($event))"
          />
        </fieldset>
      </div>
    </section>

    <!-- Trigger timing -->
    <section class="border-base-200 space-y-1 border-t pt-5">
      <div class="mb-3 flex items-center gap-2">
        <Icon
          icon="mdi:bell-badge-outline"
          class="text-primary shrink-0 text-lg"
          aria-hidden="true"
        />
        <h3 class="text-sm font-semibold">{{ t("settings.notification.sections.triggers") }}</h3>
      </div>

      <div
        class="grid grid-cols-1 items-center gap-2 border-b border-base-200 py-3 last:border-b-0 md:grid-cols-[1fr_auto] md:gap-4"
      >
        <label class="text-sm" for="notify-on-complete">
          {{ t("settings.notification.onComplete") }}
        </label>
        <input
          id="notify-on-complete"
          type="checkbox"
          class="toggle toggle-primary"
          :checked="settings.notification.notifyOnComplete"
          @change="
            handleSettingChange('notification', 'notifyOnComplete', getCheckboxValue($event))
          "
        />
      </div>

      <div
        class="grid grid-cols-1 items-center gap-2 border-b border-base-200 py-3 last:border-b-0 md:grid-cols-[1fr_auto] md:gap-4"
      >
        <label class="text-sm" for="notify-on-error">
          {{ t("settings.notification.onError") }}
        </label>
        <input
          id="notify-on-error"
          type="checkbox"
          class="toggle toggle-primary"
          :checked="settings.notification.notifyOnError"
          @change="handleSettingChange('notification', 'notifyOnError', getCheckboxValue($event))"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { testNotificationApi } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useSettingsStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import type { SettingsModel } from "@/types/settingsModel"

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

  return (
    notification.externalNotification &&
    !notification.webhook &&
    !notification.systemNotification &&
    !notification.browserNotification
  )
})

type EditableCategory = Exclude<keyof SettingsModel, "about">
type NotificationMethod = SettingsModel["notification"]["method"]
type NotificationContentType = SettingsModel["notification"]["contentType"]

function getInputValue(event: Event): string {
  const target = event.target
  return target instanceof HTMLInputElement ? target.value : ""
}

function getTextareaValue(event: Event): string {
  const target = event.target
  return target instanceof HTMLTextAreaElement ? target.value : ""
}

function getCheckboxValue(event: Event): boolean {
  const target = event.target
  return target instanceof HTMLInputElement ? target.checked : false
}

function getSelectValue(event: Event): string {
  const target = event.target
  return target instanceof HTMLSelectElement ? target.value : ""
}

function isNotificationMethod(value: string): value is NotificationMethod {
  return value === "POST" || value === "GET"
}

function isNotificationContentType(value: string): value is NotificationContentType {
  return value === "application/json" || value === "application/x-www-form-urlencoded"
}

async function handleSettingChange<K extends EditableCategory, P extends keyof SettingsModel[K]>(
  category: K,
  key: P,
  value: SettingsModel[K][P],
) {
  await settingsStore.updateSetting(category, key, value)
}

function handleMethodChange(event: Event) {
  const value = getSelectValue(event)
  if (!isNotificationMethod(value)) {
    return
  }
  void handleSettingChange("notification", "method", value)
}

function handleContentTypeChange(event: Event) {
  const value = getSelectValue(event)
  if (!isNotificationContentType(value)) {
    return
  }
  void handleSettingChange("notification", "contentType", value)
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
  const [result, err] = await tryCatch(() => testNotificationApi())
  if (err) {
    showGlobalMessage("error", t("settings.notification.testError"))
    console.error(err)
    return
  }
  if (result.status !== "success") {
    showGlobalMessage("error", t("settings.notification.testResult", { message: result.message }))
  }
}
</script>
