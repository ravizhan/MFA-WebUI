<template>
  <div v-if="executions.length === 0" class="text-center py-6 opacity-50">
    <Icon icon="mdi:inbox" class="text-3xl mx-auto mb-2" />
    <p>{{ t("settings.scheduler.noHistory") }}</p>
  </div>
  <div v-else class="space-y-3">
    <div v-for="exec in executions" :key="exec.id" class="flex gap-3 items-start">
      <div
        class="w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-1"
        :class="statusBgClass(exec.status)"
      >
        <Icon
          :icon="getStatusIcon(exec.status)"
          class="text-lg"
          :class="statusTextClass(exec.status)"
        />
      </div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center justify-between gap-2">
          <span class="font-medium text-sm truncate">{{ exec.task_name }}</span>
          <span class="text-xs opacity-50 shrink-0">{{ formatDateTimeText(exec.started_at) }}</span>
        </div>
        <div class="flex items-center gap-2 text-xs">
          <span
            class="px-1.5 py-0.5 rounded text-[10px] leading-tight"
            :class="originBadgeClass(exec.origin)"
          >
            {{ getOriginLabelText(exec.origin) }}
          </span>
          <span :class="statusTextClass(exec.status)">
            {{ getStatusLabelText(exec.status) }}
          </span>
        </div>
        <div v-if="exec.blocker_task_name" class="text-xs text-warning opacity-80">
          {{
            t("settings.scheduler.history.skippedBy", {
              name: exec.blocker_task_name,
            })
          }}
        </div>
        <div v-if="exec.error_message" class="text-xs text-error opacity-80">
          {{ exec.error_message }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import type { ExecutionStatus, TaskExecution, ExecutionOrigin } from "@/types/schedulerModel"
import {
  formatDateTime,
  getStatusIcon,
  getStatusLabel,
  getStatusType,
  getOriginLabel,
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

function getOriginLabelText(origin: ExecutionOrigin): string {
  return getOriginLabel(t, origin)
}

function statusBgClass(status: ExecutionStatus): string {
  const type = getStatusType(status)
  if (type === "success") return "bg-success/20"
  if (type === "error") return "bg-error/20"
  if (type === "warning") return "bg-warning/20"
  return "bg-info/20"
}

function statusTextClass(status: ExecutionStatus): string {
  const type = getStatusType(status)
  if (type === "success") return "text-success"
  if (type === "error") return "text-error"
  if (type === "warning") return "text-warning"
  return "text-info"
}

function originBadgeClass(origin: ExecutionOrigin): string {
  if (origin === "manual") return "bg-primary/10 text-primary"
  if (origin === "native") return "bg-secondary/10 text-secondary"
  return "bg-accent/10 text-accent"
}
</script>
