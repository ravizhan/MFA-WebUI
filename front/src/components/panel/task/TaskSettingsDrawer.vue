<template>
  <n-drawer
    :show="indexStore.TaskSettingsDrawerVisible"
    placement="right"
    width="100%"
    :mask-closable="true"
    @update:show="indexStore.setTaskSettingsDrawerVisible"
  >
    <n-drawer-content :title="drawerTitle" closable>
      <n-space vertical size="large">
        <n-card hoverable content-style="padding: 0;" class="overflow-hidden">
          <TaskOptionPanel
            :current-task-id="selectedTaskId"
            :options="configStore.options"
            :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
            :no-options-text="t('settings.scheduler.dialog.noOptions')"
          />
        </n-card>
        <TaskDescriptionCard />
      </n-space>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
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
