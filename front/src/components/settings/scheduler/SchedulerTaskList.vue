<template>
  <div v-if="tasks.length === 0" class="text-center py-6 opacity-50">
    <Icon icon="mdi:inbox" class="text-3xl mx-auto mb-2" />
    <p>{{ t("settings.scheduler.noTasks") }}</p>
  </div>
  <div v-else class="space-y-2">
    <div
      v-for="task in tasks"
      :key="task.id"
      class="card bg-base-100 shadow-sm hover:shadow-md transition-shadow"
    >
      <div class="card-body p-3">
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3 flex-1 min-w-0">
            <input
              type="checkbox"
              class="toggle toggle-primary toggle-sm"
              :checked="task.enabled"
              @change="emit('toggle', task.id, ($event.target as HTMLInputElement).checked)"
            />
            <div class="min-w-0">
              <div class="font-medium truncate">{{ task.name }}</div>
              <div class="text-xs opacity-60">{{ task.description }}</div>
              <div class="flex flex-wrap gap-x-3 text-xs opacity-50 mt-1">
                <span>
                  {{ t("settings.scheduler.trigger") }}{{ t("common.colon") }}
                  {{ formatTriggerText(task.trigger_type, task.trigger_config) }}
                </span>
                <span>
                  {{ t("settings.scheduler.nextRun") }}{{ t("common.colon") }}
                  {{ formatDateTimeText(task.next_run_time) }}
                </span>
              </div>
            </div>
          </div>
          <div class="flex gap-1 shrink-0">
            <button class="btn btn-ghost btn-xs" @click="emit('edit', task)">
              {{ t("common.edit") }}
            </button>
            <button class="btn btn-ghost btn-xs text-error" @click="emit('delete', task.id)">
              {{ t("common.delete") }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { formatDateTime, formatTrigger } from "@/utils/scheduler/display"
import type { ScheduledTask, TriggerConfig, TriggerType } from "@/types/schedulerModel"

const { tasks } = defineProps<{
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
