<template>
  <div class="flex p-5 gap-6 h-[80vh] overflow-y-auto max-md:flex-col max-md:p-3">
    <div
      class="sticky top-5 w-45 shrink-0 h-fit max-md:relative max-md:top-0 max-md:w-full max-md:mb-4"
    >
      <n-anchor
        :show-rail="true"
        :show-background="true"
        :bound="80"
        type="block"
        offset-target="#setting-content"
      >
        <n-anchor-link :title="t('settings.anchor.update')" href="#update-settings">
          <template #icon
            ><n-icon><div class="i-mdi-update" /></n-icon
          ></template>
        </n-anchor-link>
        <n-anchor-link :title="t('settings.anchor.runtime')" href="#runtime-settings">
          <template #icon
            ><n-icon><div class="i-mdi-cog-play" /></n-icon
          ></template>
        </n-anchor-link>
        <n-anchor-link :title="t('settings.anchor.scheduler')" href="#scheduler-settings">
          <template #icon
            ><n-icon><div class="i-mdi-clock-outline" /></n-icon
          ></template>
        </n-anchor-link>
        <n-anchor-link :title="t('settings.anchor.ui')" href="#ui-settings">
          <template #icon
            ><n-icon><div class="i-mdi-palette" /></n-icon
          ></template>
        </n-anchor-link>
        <n-anchor-link :title="t('settings.anchor.notification')" href="#notification-settings">
          <template #icon
            ><n-icon><div class="i-mdi-bell" /></n-icon
          ></template>
        </n-anchor-link>
        <n-anchor-link :title="t('settings.anchor.about')" href="#about">
          <template #icon
            ><n-icon><div class="i-mdi-information" /></n-icon
          ></template>
        </n-anchor-link>
      </n-anchor>
    </div>

    <div id="setting-content" class="flex-1 overflow-y-auto max-md:max-w-full">
      <n-scrollbar>
        <UpdateSettingsSection @show-update="handleShowUpdate" />
        <RuntimeSettingsSection />
        <SchedulerSettingsSection
          @create-task="openCreateTaskDialog"
          @edit-task="openEditTaskDialog"
        />
        <UISettingsSection />
        <NotificationSettingsSection />
        <AboutSettingsSection />
      </n-scrollbar>
    </div>

    <SchedulerTaskDialog
      v-model:show="showTaskDialog"
      :task="editingTask"
      @saved="handleTaskSaved"
    />
    <UpdateDialog v-model:show="showUpdateDialog" :update-info="updateInfo" />
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useI18n } from "vue-i18n"
import SchedulerTaskDialog from "@/components/settings/dialogs/SchedulerTaskDialog.vue"
import UpdateDialog from "@/components/settings/dialogs/UpdateDialog.vue"
import AboutSettingsSection from "@/components/settings/sections/AboutSettingsSection.vue"
import NotificationSettingsSection from "@/components/settings/sections/NotificationSettingsSection.vue"
import RuntimeSettingsSection from "@/components/settings/sections/RuntimeSettingsSection.vue"
import SchedulerSettingsSection from "@/components/settings/sections/SchedulerSettingsSection.vue"
import UISettingsSection from "@/components/settings/sections/UISettingsSection.vue"
import UpdateSettingsSection from "@/components/settings/sections/UpdateSettingsSection.vue"
import { useSchedulerStore } from "@/stores"
import type { ScheduledTask } from "@/types/scheduler/model"
import type { UpdateInfo } from "@/services/api"

const { t } = useI18n()
const schedulerStore = useSchedulerStore()
const showTaskDialog = ref(false)
const editingTask = ref<ScheduledTask | null>(null)
const showUpdateDialog = ref(false)
const updateInfo = ref<UpdateInfo | null>(null)

function openCreateTaskDialog() {
  editingTask.value = null
  showTaskDialog.value = true
}

function openEditTaskDialog(task: ScheduledTask) {
  editingTask.value = task
  showTaskDialog.value = true
}

function handleShowUpdate(info: UpdateInfo) {
  updateInfo.value = info
  showUpdateDialog.value = true
}

function handleTaskSaved() {
  void schedulerStore.fetchTasks()
  void schedulerStore.fetchExecutions()
}
</script>

<style scoped>
.n-anchor-link {
  line-height: 2;
}
</style>
