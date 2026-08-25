<template>
  <div class="space-y-6">
    <!-- Channels + test -->
    <section class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex min-w-0 items-center gap-2">
          <NIcon size="18" aria-hidden="true">
            <NotificationsOutline />
          </NIcon>
          <h3 class="text-sm font-semibold">{{ t("settings.notification.sections.channels") }}</h3>
        </div>
        <NButton
          type="primary"
          size="small"
          :disabled="isTestNotificationDisabled"
          :title="t('settings.notification.test')"
          :aria-label="t('settings.notification.test')"
          @click="testNotification"
        >
          <template #icon>
            <NIcon size="18" aria-hidden="true"><NotificationsOutline /></NIcon>
          </template>
          {{ t("settings.notification.test") }}
        </NButton>
      </div>

      <div class="flex flex-wrap gap-2">
        <NCheckbox
          class="rounded-lg px-3 py-2 transition-colors"
          :class="{ 'bg-primary/5': settings.notification.systemNotification }"
          :checked="settings.notification.systemNotification"
          @update:checked="handleSettingChange('notification', 'systemNotification', $event)"
        >
          <span class="flex items-center gap-2">
            <NIcon size="18" aria-hidden="true">
              <DesktopOutline />
            </NIcon>
            <span class="text-sm">{{ t("settings.notification.system") }}</span>
          </span>
        </NCheckbox>

        <NCheckbox
          class="rounded-lg px-3 py-2 transition-colors"
          :class="{ 'bg-primary/5': settings.notification.browserNotification }"
          :checked="settings.notification.browserNotification"
          @update:checked="handleBrowserNotificationChange"
        >
          <span class="flex items-center gap-2">
            <NIcon size="18" aria-hidden="true">
              <GlobeOutline />
            </NIcon>
            <span class="text-sm">{{ t("settings.notification.browser") }}</span>
          </span>
        </NCheckbox>

        <NCheckbox
          class="rounded-lg px-3 py-2 transition-colors"
          :class="{ 'bg-primary/5': settings.notification.externalNotification }"
          :checked="settings.notification.externalNotification"
          @update:checked="handleSettingChange('notification', 'externalNotification', $event)"
        >
          <span class="flex items-center gap-2">
            <NIcon size="18" aria-hidden="true">
              <LinkOutline />
            </NIcon>
            <span class="text-sm">{{ t("settings.notification.external") }}</span>
          </span>
        </NCheckbox>
      </div>
    </section>

    <!-- External connection (collapses when off) -->
    <section v-if="settings.notification.externalNotification" class="space-y-4 pt-5">
      <div class="flex items-center gap-2">
        <NIcon size="18" aria-hidden="true">
          <LinkOutline />
        </NIcon>
        <h3 class="text-sm font-semibold">
          {{ t("settings.notification.sections.external") }}
        </h3>
      </div>

      <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div class="md:col-span-2">
          <label class="mb-2 block text-sm font-medium">
            {{ t("settings.notification.fields.url") }}
          </label>
          <NInput
            :value="settings.notification.webhook"
            class="w-full font-mono text-sm"
            placeholder="https://..."
            :input-props="{ autocomplete: 'off', spellcheck: false }"
            @update:value="handleSettingChange('notification', 'webhook', $event)"
          />
        </div>

        <div>
          <label class="mb-2 block text-sm font-medium">
            {{ t("settings.notification.fields.method") }}
          </label>
          <NSelect
            :value="settings.notification.method"
            class="w-full"
            :options="methodOptions"
            @update:value="handleMethodChange"
          />
        </div>

        <div v-if="settings.notification.method !== 'GET'">
          <label class="mb-2 block text-sm font-medium">
            {{ t("settings.notification.fields.contentType") }}
          </label>
          <NSelect
            :value="settings.notification.contentType"
            class="w-full"
            :options="contentTypeOptions"
            @update:value="handleContentTypeChange"
          />
        </div>

        <div class="md:col-span-2">
          <label class="mb-2 block text-sm font-medium">
            {{ t("settings.notification.fields.headers") }}
          </label>
          <NInput
            :value="settings.notification.headers"
            class="w-full font-mono text-sm"
            placeholder='{"Authorization":"Bearer ..."}'
            :input-props="{ autocomplete: 'off', spellcheck: false }"
            @update:value="handleSettingChange('notification', 'headers', $event)"
          />
        </div>

        <div class="md:col-span-2">
          <label class="mb-2 block text-sm font-medium">
            {{ t("settings.notification.fields.body") }}
          </label>
          <NInput
            type="textarea"
            :value="settings.notification.body"
            class="min-h-24 w-full font-mono text-sm"
            placeholder='{"desp":"{{message}}","title":"{{title}}"}'
            :autosize="{ minRows: 4 }"
            :input-props="{ spellcheck: false }"
            @update:value="handleSettingChange('notification', 'body', $event)"
          />
        </div>

        <div>
          <label class="mb-2 block text-sm font-medium">
            {{ t("settings.notification.fields.username") }}
          </label>
          <NInput
            :value="settings.notification.username"
            class="w-full"
            :input-props="{ autocomplete: 'username' }"
            @update:value="handleSettingChange('notification', 'username', $event)"
          />
        </div>

        <div>
          <label class="mb-2 block text-sm font-medium">
            {{ t("settings.notification.fields.password") }}
          </label>
          <NInput
            type="password"
            :value="settings.notification.password"
            class="w-full"
            :input-props="{ autocomplete: 'current-password' }"
            @update:value="handleSettingChange('notification', 'password', $event)"
          />
        </div>
      </div>
    </section>

    <!-- Trigger timing -->
    <section class="space-y-1 pt-5">
      <div class="mb-3 flex items-center gap-2">
        <NBadge dot>
          <NIcon size="18" aria-hidden="true">
            <NotificationsOutline />
          </NIcon>
        </NBadge>
        <h3 class="text-sm font-semibold">{{ t("settings.notification.sections.triggers") }}</h3>
      </div>

      <div class="grid grid-cols-1 items-center gap-2 py-3 md:grid-cols-[1fr_auto] md:gap-4">
        <label class="text-sm" for="notify-on-complete">
          {{ t("settings.notification.onComplete") }}
        </label>
        <NSwitch
          id="notify-on-complete"
          :value="settings.notification.notifyOnComplete"
          :aria-label="t('settings.notification.onComplete')"
          @update:value="handleSettingChange('notification', 'notifyOnComplete', $event)"
        />
      </div>

      <div class="grid grid-cols-1 items-center gap-2 py-3 md:grid-cols-[1fr_auto] md:gap-4">
        <label class="text-sm" for="notify-on-error">
          {{ t("settings.notification.onError") }}
        </label>
        <NSwitch
          id="notify-on-error"
          :value="settings.notification.notifyOnError"
          :aria-label="t('settings.notification.onError')"
          @update:value="handleSettingChange('notification', 'notifyOnError', $event)"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { NBadge, NButton, NCheckbox, NIcon, NInput, NSelect, NSwitch } from "naive-ui"
import { DesktopOutline, GlobeOutline, LinkOutline, NotificationsOutline } from "@vicons/ionicons5"
import { testNotificationApi } from "@/services/api"
import { showGlobalMessage } from "@/services/feedback/message"
import { useSettingsStore } from "@/stores"
import { tryCatch } from "@/utils/tryCatch"
import type { SettingsModel } from "@/types/settingsModel"

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

const methodOptions = computed(() => [
  { label: t("settings.notification.fields.post"), value: "POST" },
  { label: t("settings.notification.fields.get"), value: "GET" },
])

const contentTypeOptions = computed(() => [
  { label: t("settings.notification.fields.json"), value: "application/json" },
  {
    label: t("settings.notification.fields.formUrlencoded"),
    value: "application/x-www-form-urlencoded",
  },
])

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

function handleMethodChange(value: string | number | null) {
  if (typeof value !== "string" || !isNotificationMethod(value)) {
    return
  }
  void handleSettingChange("notification", "method", value)
}

function handleContentTypeChange(value: string | number | null) {
  if (typeof value !== "string" || !isNotificationContentType(value)) {
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
