<template>
  <NEmpty
    v-if="tasks.length === 0"
    size="small"
    :description="t('settings.scheduler.noTasks')"
    class="py-6"
  >
    <template #icon>
      <NIcon size="30"><FileTrayOutline /></NIcon>
    </template>
  </NEmpty>
  <div v-else class="space-y-2">
    <SchedulerTaskRow
      v-for="task in tasks"
      :key="task.id"
      :task="task"
      @toggle="handleToggle"
      @edit="handleEdit"
      @delete="handleDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NEmpty, NIcon } from "naive-ui"
import { FileTrayOutline } from "@vicons/ionicons5"
import type { ScheduledTask } from "@/types/schedulerModel"
import SchedulerTaskRow from "./SchedulerTaskRow.vue"

const { tasks } = defineProps<{
  tasks: ScheduledTask[]
}>()

const emit = defineEmits<{
  (e: "toggle", taskId: string, enabled: boolean): void
  (e: "edit", task: ScheduledTask): void
  (e: "delete", taskId: string): void
}>()

const { t } = useI18n()

function handleToggle(taskId: string, enabled: boolean) {
  emit("toggle", taskId, enabled)
}

function handleEdit(task: ScheduledTask) {
  emit("edit", task)
}

function handleDelete(taskId: string) {
  emit("delete", taskId)
}
</script>
