<template>
  <div class="flex flex-col lg:flex-row gap-4 max-w-screen-xl mx-auto">
    <!-- Left sidebar: settings sections -->
    <div class="lg:w-64 shrink-0">
      <!-- Mobile: horizontal scroll -->
      <div class="flex lg:flex-col gap-1 overflow-x-auto lg:overflow-visible pb-2 lg:pb-0">
        <button
          v-for="section in sections"
          :key="section.id"
          class="flex items-center gap-2 px-3 py-2 rounded-lg text-sm whitespace-nowrap lg:whitespace-normal transition-colors"
          :class="
            activeSection === section.id ? 'bg-primary text-primary-content' : 'hover:bg-base-300'
          "
          @click="activeSection = section.id"
        >
          <Icon :icon="section.icon" class="text-lg" />
          {{ section.label }}
        </button>
      </div>
    </div>

    <!-- Right: active section content -->
    <div class="flex-1 min-w-0">
      <!-- Update -->
      <div v-if="activeSection === 'update'" class="card bg-base-100 shadow-xl">
        <div class="card-body">
          <h2 class="card-title">
            <Icon icon="mdi:update" class="text-primary text-xl" />
            {{ t("settings.update.title") }}
          </h2>
          <UpdateSettingsSection @show-update="handleShowUpdate" />
        </div>
      </div>

      <!-- Runtime -->
      <div v-if="activeSection === 'runtime'" class="card bg-base-100 shadow-xl">
        <div class="card-body">
          <h2 class="card-title">
            <Icon icon="mdi:cog-play" class="text-primary text-xl" />
            {{ t("settings.runtime.title") }}
          </h2>
          <RuntimeSettingsSection />
        </div>
      </div>

      <!-- UI -->
      <div v-if="activeSection === 'ui'" class="card bg-base-100 shadow-xl">
        <div class="card-body">
          <h2 class="card-title">
            <Icon icon="mdi:palette" class="text-primary text-xl" />
            {{ t("settings.ui.title") }}
          </h2>
          <UISettingsSection />
        </div>
      </div>

      <!-- Notification -->
      <div v-if="activeSection === 'notification'" class="card bg-base-100 shadow-xl">
        <div class="card-body">
          <h2 class="card-title">
            <Icon icon="mdi:bell" class="text-primary text-xl" />
            {{ t("settings.notification.title") }}
          </h2>
          <NotificationSettingsSection />
        </div>
      </div>

      <!-- About -->
      <div v-if="activeSection === 'about'" class="card bg-base-100 shadow-xl">
        <div class="card-body">
          <h2 class="card-title">
            <Icon icon="mdi:information" class="text-primary text-xl" />
            {{ t("settings.about.title") }}
          </h2>
          <AboutSettingsSection />
        </div>
      </div>
    </div>

    <UpdateDialog v-model:show="showUpdateDialog" :update-info="updateInfo" />
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import UpdateDialog from "@/components/settings/dialogs/UpdateDialog.vue"
import AboutSettingsSection from "@/components/settings/sections/AboutSettingsSection.vue"
import NotificationSettingsSection from "@/components/settings/sections/NotificationSettingsSection.vue"
import RuntimeSettingsSection from "@/components/settings/sections/RuntimeSettingsSection.vue"
import UISettingsSection from "@/components/settings/sections/UISettingsSection.vue"
import UpdateSettingsSection from "@/components/settings/sections/UpdateSettingsSection.vue"
import type { UpdateInfo } from "@/services/api"

const { t } = useI18n()
const activeSection = ref("update")
const showUpdateDialog = ref(false)
const updateInfo = ref<UpdateInfo | null>(null)

const sections = [
  { id: "update", label: t("settings.anchor.update"), icon: "mdi:update" },
  { id: "runtime", label: t("settings.anchor.runtime"), icon: "mdi:cog-play" },
  { id: "ui", label: t("settings.anchor.ui"), icon: "mdi:palette" },
  { id: "notification", label: t("settings.anchor.notification"), icon: "mdi:bell" },
  { id: "about", label: t("settings.anchor.about"), icon: "mdi:information" },
]

function handleShowUpdate(info: UpdateInfo) {
  updateInfo.value = info
  showUpdateDialog.value = true
}
</script>
