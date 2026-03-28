<template>
  <n-card
    id="scheduler-settings"
    class="mb-6 scroll-mt-5 last:mb-0"
    :title="t('settings.scheduler.title')"
  >
    <template #header-extra>
      <n-button size="small" type="primary" @click="emit('create-task')">
        <template #icon>
          <n-icon><div class="i-mdi-plus" /></n-icon>
        </template>
        {{ t("settings.scheduler.create") }}
      </n-button>
    </template>

    <n-collapse>
      <n-collapse-item :title="t('settings.scheduler.taskList')" name="tasks">
        <SchedulerTaskList
          :tasks="schedulerStore.tasks"
          @toggle="handleToggleTask"
          @edit="(task) => emit('edit-task', task)"
          @delete="handleDeleteTask"
        />
      </n-collapse-item>
      <n-collapse-item :title="t('settings.scheduler.history')" name="history">
        <SchedulerExecutionHistory :executions="schedulerStore.executions" />
      </n-collapse-item>
    </n-collapse>
  </n-card>
</template>

<script setup lang="ts">
import { onMounted } from "vue"
import { useDialog, useMessage } from "naive-ui"
import { useI18n } from "vue-i18n"
import SchedulerExecutionHistory from "@/components/settings/scheduler/SchedulerExecutionHistory.vue"
import SchedulerTaskList from "@/components/settings/scheduler/SchedulerTaskList.vue"
import { useSchedulerStore } from "@/stores"
import type { ScheduledTask } from "@/types/scheduler/model"

const emit = defineEmits<{
  (e: "create-task"): void
  (e: "edit-task", task: ScheduledTask): void
}>()

const { t } = useI18n()
const dialog = useDialog()
const message = useMessage()
const schedulerStore = useSchedulerStore()

onMounted(() => {
  void schedulerStore.fetchTasks()
  void schedulerStore.fetchExecutions()
})

async function handleToggleTask(taskId: string, enabled: boolean) {
  await schedulerStore.toggleTask(taskId, enabled)
  if (schedulerStore.error) {
    message.error(schedulerStore.error)
  }
}

function handleDeleteTask(taskId: string) {
  dialog.warning({
    title: t("common.delete"),
    content: t("settings.scheduler.deleteConfirm"),
    positiveText: t("common.confirm"),
    negativeText: t("common.cancel"),
    onPositiveClick: async () => {
      const success = await schedulerStore.deleteTask(taskId)
      if (success) {
        message.success(t("settings.scheduler.deleted"))
      } else {
        message.error(schedulerStore.error || t("common.fail"))
      }
    },
  })
}
</script>
