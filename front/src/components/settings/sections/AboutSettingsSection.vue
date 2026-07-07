<template>
  <div class="space-y-4">
    <div class="overflow-x-auto">
      <table class="table table-sm">
        <tbody>
          <tr>
            <td class="font-medium text-sm">{{ t("settings.about.version") }}</td>
            <td class="text-sm">{{ settings.about.version || t("common.unknown") }}</td>
          </tr>
          <tr>
            <td class="font-medium text-sm">{{ t("settings.about.author") }}</td>
            <td class="text-sm">
              <a
                v-if="settings.about.author"
                :href="`https://github.com/${settings.about.author}`"
                target="_blank"
                class="link link-primary flex items-center gap-1"
              >
                <Icon icon="mdi:github" class="text-lg" />
                {{ settings.about.author }}
              </a>
              <span v-else>{{ t("common.unknown") }}</span>
            </td>
          </tr>
          <tr>
            <td class="font-medium text-sm">{{ t("settings.about.license") }}</td>
            <td class="text-sm">{{ settings.about.license || "MIT" }}</td>
          </tr>
          <tr>
            <td class="font-medium text-sm">{{ t("settings.about.homepage") }}</td>
            <td class="text-sm">
              <a
                :href="settings.about.github || 'https://github.com/ravizhan/MWU'"
                target="_blank"
                class="link link-primary flex items-center gap-1"
              >
                <Icon icon="mdi:github" class="text-lg" />
                {{ settings.about.github || "https://github.com/ravizhan/MWU" }}
              </a>
            </td>
          </tr>
          <tr>
            <td class="font-medium text-sm">{{ t("settings.about.issue") }}</td>
            <td class="text-sm">
              <a
                :href="settings.about.issueUrl || 'https://github.com/ravizhan/MWU/issues'"
                target="_blank"
                class="link link-primary flex items-center gap-1"
              >
                <Icon icon="mdi:bug" class="text-lg" />
                GitHub Issues
              </a>
            </td>
          </tr>
          <tr v-if="settings.about.contact">
            <td class="font-medium text-sm">{{ t("settings.about.contact") }}</td>
            <td class="text-sm">{{ settings.about.contact }}</td>
          </tr>
          <tr>
            <td class="font-medium text-sm">{{ t("settings.about.description") }}</td>
            <td class="text-sm">
              {{ settings.about.description || t("settings.about.defaultDescription") }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="divider" />

    <button class="btn btn-warning btn-sm" @click="handleResetSettings">
      {{ t("settings.about.reset") }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { showGlobalMessage } from "@/services/feedback/message"
import { useSettingsStore } from "@/stores"

const { t } = useI18n()
const settingsStore = useSettingsStore()
const settings = computed(() => settingsStore.settings)

function handleResetSettings() {
  if (confirm(t("settings.about.resetConfirm"))) {
    void settingsStore.resetSettings().then((success) => {
      if (success) {
        showGlobalMessage("success", t("settings.about.resetSuccess"))
      }
    })
  }
}
</script>
