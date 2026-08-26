<template>
  <div>
    <div class="flex items-center justify-between gap-2">
      <span class="flex items-center gap-2 min-w-0">
        <span class="font-medium text-sm truncate">{{ execution.task_name }}</span>
        <NTag size="small" :type="originTagType(execution.origin)" class="shrink-0">
          <template #icon>
            <NIcon size="14"><component :is="originIcon(execution.origin)" /></NIcon>
          </template>
          {{ getOriginLabelText(execution.origin) }}
        </NTag>
      </span>
      <span class="text-xs opacity-50 shrink-0">{{
        formatDateTimeText(execution.started_at)
      }}</span>
    </div>
    <div class="mt-1">
      <NTag size="small" :type="getStatusType(execution.status)">
        <template #icon>
          <NIcon size="14" :class="{ 'animate-spin': execution.status === 'running' }">
            <component :is="statusIcon(execution.status)" />
          </NIcon>
        </template>
        {{ getStatusLabelText(execution.status) }}
      </NTag>
    </div>
    <div v-if="execution.blocker_task_name" class="text-xs" style="color: var(--warning-color)">
      {{ t("settings.scheduler.history.skippedBy", { name: execution.blocker_task_name }) }}
    </div>
    <div
      v-if="execution.error_message"
      class="text-xs opacity-80"
      style="color: var(--error-color)"
    >
      {{ execution.error_message }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import type { Component } from "vue"
import { NIcon, NTag } from "naive-ui"
import {
  AppsOutline,
  ArrowUpCircleOutline,
  CalendarOutline,
  CheckmarkCircleOutline,
  CloseCircleOutline,
  HelpCircleOutline,
  MoonOutline,
  PauseCircleOutline,
  PersonOutline,
  PersonRemoveOutline,
  RefreshOutline,
} from "@vicons/ionicons5"
import type { ExecutionOrigin, ExecutionStatus, TaskExecution } from "@/types/schedulerModel"
import {
  formatDateTime,
  getOriginLabel,
  getStatusLabel,
  getStatusType,
} from "@/utils/scheduler/display"

const { execution } = defineProps<{
  execution: TaskExecution
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

function statusIcon(status: ExecutionStatus): Component {
  const map: Record<string, Component> = {
    success: CheckmarkCircleOutline,
    failed: CloseCircleOutline,
    running: RefreshOutline,
    stopped: PauseCircleOutline,
    skipped_busy_manual: PersonRemoveOutline,
    skipped_busy_scheduled: CalendarOutline,
    skipped_update_in_progress: ArrowUpCircleOutline,
  }
  return map[status] || HelpCircleOutline
}

function originIcon(origin: ExecutionOrigin): Component {
  const map: Record<string, Component> = {
    manual: PersonOutline,
    in_app: AppsOutline,
    native: MoonOutline,
  }
  return map[origin] || HelpCircleOutline
}

function originTagType(origin: ExecutionOrigin): "success" | "info" | "default" {
  const map: Record<string, "success" | "info" | "default"> = {
    manual: "info",
    in_app: "default",
    native: "success",
  }
  return map[origin] || "default"
}
</script>
