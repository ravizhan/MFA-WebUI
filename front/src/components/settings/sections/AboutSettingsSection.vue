<template>
  <n-card id="about" class="mb-6 scroll-mt-5 last:mb-0" :title="t('settings.about.title')">
    <n-descriptions bordered :column="1">
      <n-descriptions-item :label="t('settings.about.version')">
        {{ settings.about.version || t("common.unknown") }}
      </n-descriptions-item>
      <n-descriptions-item :label="t('settings.about.author')">
        {{ settings.about.author || t("common.unknown") }}
      </n-descriptions-item>
      <n-descriptions-item :label="t('settings.about.license')">
        {{ settings.about.license || "MIT" }}
      </n-descriptions-item>
      <n-descriptions-item :label="t('settings.about.homepage')">
        <n-button
          text
          tag="a"
          :href="settings.about.github || 'https://github.com/ravizhan/MWU'"
          target="_blank"
          type="primary"
        >
          <template #icon>
            <n-icon><div class="i-mdi-github" /></n-icon>
          </template>
          {{ settings.about.github || "https://github.com/ravizhan/MWU" }}
        </n-button>
      </n-descriptions-item>
      <n-descriptions-item :label="t('settings.about.issue')">
        <n-button
          text
          tag="a"
          :href="settings.about.issueUrl || 'https://github.com/ravizhan/MWU/issues'"
          target="_blank"
          type="primary"
        >
          <template #icon>
            <n-icon><div class="i-mdi-bug" /></n-icon>
          </template>
          GitHub Issues
        </n-button>
      </n-descriptions-item>
      <n-descriptions-item :label="t('settings.about.contact')" v-if="settings.about.contact">
        {{ settings.about.contact }}
      </n-descriptions-item>
      <n-descriptions-item :label="t('settings.about.description')">
        {{ settings.about.description || t("settings.about.defaultDescription") }}
      </n-descriptions-item>
    </n-descriptions>
    <n-divider />
    <n-space>
      <n-button type="warning" @click="handleResetSettings">{{
        t("settings.about.reset")
      }}</n-button>
    </n-space>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useDialog, useMessage } from "naive-ui"
import { useI18n } from "vue-i18n"
import { useSettingsStore } from "@/stores"

const { t } = useI18n()
const dialog = useDialog()
const message = useMessage()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

function handleResetSettings() {
  dialog.warning({
    title: t("common.confirm"),
    content: t("settings.about.resetConfirm"),
    positiveText: t("common.confirm"),
    negativeText: t("common.cancel"),
    onPositiveClick: async () => {
      const success = await settingsStore.resetSettings()
      if (success) {
        message.success(t("settings.about.resetSuccess"))
      }
    },
  })
}
</script>
