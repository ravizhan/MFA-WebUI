<template>
  <n-empty v-if="executions.length === 0" :description="t('settings.scheduler.noHistory')" />
  <n-timeline v-else>
    <n-timeline-item
      v-for="exec in executions"
      :key="exec.id"
      :type="getStatusType(exec.status)"
      :title="exec.task_name"
      :time="formatDateTimeText(exec.started_at)"
    >
      <template #icon>
        <n-icon>
          <div :class="getStatusIcon(exec.status)" />
        </n-icon>
      </template>
      <n-text :type="getStatusType(exec.status)">
        {{ getStatusLabelText(exec.status) }}
      </n-text>
      <n-text v-if="exec.error_message" type="error" depth="3">
        {{ exec.error_message }}
      </n-text>
    </n-timeline-item>
  </n-timeline>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import type { ExecutionStatus, TaskExecution } from "@/types/scheduler/model"
import {
  formatDateTime,
  getStatusIcon,
  getStatusLabel,
  getStatusType,
} from "@/utils/scheduler/display"

defineProps<{
  executions: TaskExecution[]
}>()

const { t, locale } = useI18n()

function formatDateTimeText(dateStr?: string): string {
  return formatDateTime(t, locale.value, dateStr)
}

function getStatusLabelText(status: ExecutionStatus): string {
  return getStatusLabel(t, status)
}
</script>
