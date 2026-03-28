<template>
  <n-empty v-if="tasks.length === 0" :description="t('settings.scheduler.noTasks')" />
  <n-list v-else>
    <n-list-item v-for="task in tasks" :key="task.id">
      <template #prefix>
        <n-switch
          :value="task.enabled"
          @update:value="(val: boolean) => emit('toggle', task.id, val)"
        />
      </template>
      <n-thing :title="task.name" :description="task.description">
        <template #header-extra>
          <n-space>
            <n-button size="tiny" @click="emit('edit', task)">{{ t("common.edit") }}</n-button>
            <n-button size="tiny" type="error" @click="emit('delete', task.id)">{{
              t("common.delete")
            }}</n-button>
          </n-space>
        </template>
        <template #description>
          <n-space vertical size="small">
            <n-text depth="3">
              {{ t("settings.scheduler.trigger") }}:
              {{ formatTriggerText(task.trigger_type, task.trigger_config) }}
            </n-text>
            <n-text depth="3">
              {{ t("settings.scheduler.nextRun") }}: {{ formatDateTimeText(task.next_run_time) }}
            </n-text>
          </n-space>
        </template>
      </n-thing>
    </n-list-item>
  </n-list>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { formatDateTime, formatTrigger } from "@/utils/scheduler/display"
import type { ScheduledTask, TriggerConfig, TriggerType } from "@/types/scheduler/model"

const props = defineProps<{
  tasks: ScheduledTask[]
}>()

const emit = defineEmits<{
  (e: "toggle", taskId: string, enabled: boolean): void
  (e: "edit", task: ScheduledTask): void
  (e: "delete", taskId: string): void
}>()

const { t, locale } = useI18n()

function formatTriggerText(triggerType: TriggerType, triggerConfig: TriggerConfig): string {
  return formatTrigger(t, locale.value, triggerType, triggerConfig)
}

function formatDateTimeText(dateStr?: string): string {
  return formatDateTime(t, locale.value, dateStr)
}
</script>
