<template>
  <div class="space-y-3">
    <div v-if="schedulerStore.tasks.length === 0" class="text-center py-6 opacity-50">
      <NIcon size="30" class="mx-auto mb-2" style="color: var(--text-color-3)">
        <TimeOutline />
      </NIcon>
      <p class="text-sm">{{ t("settings.scheduler.noTasks") }}</p>
    </div>
    <div v-else class="space-y-2">
      <div
        v-for="task in schedulerStore.tasks.slice(0, 5)"
        :key="task.id"
        class="flex items-center gap-3 p-2 rounded-lg"
        style="background: var(--card-color)"
      >
        <div
          class="w-2 h-2 rounded-full shrink-0"
          :style="{
            backgroundColor: task.enabled ? 'var(--success-color)' : 'var(--text-color-3)',
          }"
        />
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium truncate">{{ task.name }}</div>
          <div class="text-xs opacity-60">
            {{ formatTriggerText(task.trigger_config) }}
          </div>
        </div>
        <div class="text-xs opacity-60 shrink-0">
          {{ task.enabled ? formatDateTimeText(task.next_run_time) : t("panel.health.paused") }}
        </div>
      </div>
    </div>

    <!-- Health score -->
    <NEl tag="div" class="mt-4 p-3 rounded-lg" style="background: var(--card-color)">
      <div class="flex items-center justify-between mb-2">
        <span class="text-sm font-medium">
          {{ t("nav.routines") }}{{ t("panel.health.label") }}
        </span>
        <span class="text-sm font-bold" :style="{ color: healthColor }">
          {{ healthScoreText }}
        </span>
      </div>
      <NProgress
        class="w-full"
        type="line"
        :percentage="healthScore"
        :status="healthStatus"
        :show-indicator="false"
      />
      <div class="flex justify-between text-xs opacity-60 mt-1">
        <span>{{ t("panel.health.running") }} {{ schedulerStore.enabledTasks.length }}</span>
        <span>{{ t("panel.health.total") }} {{ schedulerStore.tasks.length }}</span>
      </div>
    </NEl>

    <div class="flex gap-2">
      <RouterLink :to="{ name: 'routines' }" class="flex-1">
        <NButton secondary type="primary" size="small" block>
          <template #icon>
            <NIcon size="16"><AddCircleOutline /></NIcon>
          </template>
          {{ t("settings.scheduler.create") }}
        </NButton>
      </RouterLink>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { NButton, NEl, NIcon, NProgress } from "naive-ui"
import { AddCircleOutline, TimeOutline } from "@vicons/ionicons5"
import { useSchedulerStore } from "@/stores"
import { formatDateTime, formatTrigger } from "@/utils/scheduler/display"
import type { TriggerConfig } from "@/types/schedulerModel"

const { t, locale } = useI18n()
const schedulerStore = useSchedulerStore()

const healthScore = computed(() => {
  if (schedulerStore.tasks.length === 0) return 100
  const enabled = schedulerStore.enabledTasks.length
  return Math.round((enabled / schedulerStore.tasks.length) * 100)
})

const healthStatus = computed<"success" | "warning" | "error">(() => {
  if (healthScore.value >= 80) return "success"
  if (healthScore.value >= 50) return "warning"
  return "error"
})

const healthColor = computed(() => {
  if (healthStatus.value === "success") return "var(--success-color)"
  if (healthStatus.value === "warning") return "var(--warning-color)"
  return "var(--error-color)"
})

const healthScoreText = computed(() => `${healthScore.value}%`)

function formatTriggerText(triggerConfig: TriggerConfig): string {
  return formatTrigger(t, locale.value, triggerConfig.type, triggerConfig)
}

function formatDateTimeText(dateStr?: string): string {
  return formatDateTime(t, locale.value, dateStr)
}
</script>
