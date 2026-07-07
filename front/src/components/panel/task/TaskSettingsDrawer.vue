<template>
  <div
    class="fixed inset-0 z-50"
    :class="{ 'pointer-events-none': !indexStore.TaskSettingsDrawerVisible }"
  >
    <!-- Backdrop -->
    <div
      class="absolute inset-0 bg-black/50 transition-opacity"
      :class="indexStore.TaskSettingsDrawerVisible ? 'opacity-100' : 'opacity-0'"
      @click="indexStore.closeTaskSettingsDrawer()"
    />
    <!-- Drawer -->
    <div
      class="absolute right-0 top-0 h-full w-full max-w-md bg-base-100 shadow-2xl transform transition-transform duration-300 overflow-y-auto"
      :class="indexStore.TaskSettingsDrawerVisible ? 'translate-x-0' : 'translate-x-full'"
    >
      <div class="p-4">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-bold">{{ drawerTitle }}</h3>
          <button
            class="btn btn-ghost btn-circle btn-sm"
            @click="indexStore.closeTaskSettingsDrawer()"
          >
            <Icon icon="mdi:close" class="text-base" />
          </button>
        </div>
        <div class="space-y-4">
          <div class="card bg-base-200">
            <div class="card-body p-3">
              <TaskOptionPanel
                :current-task-id="selectedTaskId"
                :options="configStore.options"
                :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
                :no-options-text="t('settings.scheduler.dialog.noOptions')"
              />
            </div>
          </div>
          <TaskDescriptionCard />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import TaskDescriptionCard from "@/components/panel/task/TaskDescriptionCard.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import { useIndexStore, useInterfaceStore, useTaskConfigStore } from "@/stores"
import { resolveInterfaceText } from "@/utils/interface/content"

const { t, locale } = useI18n()
const configStore = useTaskConfigStore()
const indexStore = useIndexStore()
const interfaceStore = useInterfaceStore()

const selectedTaskId = computed(() => indexStore.SelectedTaskID || null)
const drawerTitle = computed(() => {
  const task = selectedTaskId.value ? interfaceStore.getTaskByEntry(selectedTaskId.value) : null
  if (!task) {
    return t("panel.taskSettings")
  }

  const taskName = resolveInterfaceText(
    interfaceStore.interface,
    locale.value,
    task.label,
    task.name,
  )
  return `${t("panel.taskSettings")} · ${taskName}`
})
</script>
