<template>
  <div class="space-y-3">
    <div v-if="schedulerStore.tasks.length === 0" class="text-center py-6 opacity-50">
      <Icon icon="mdi:clock-off" class="text-3xl mx-auto mb-2" />
      <p class="text-sm">{{ t("settings.scheduler.noTasks") }}</p>
    </div>
    <div v-else class="space-y-2">
      <div
        v-for="task in schedulerStore.tasks.slice(0, 5)"
        :key="task.id"
        class="flex items-center gap-3 p-2 rounded-lg bg-base-200"
      >
        <div
          class="w-2 h-2 rounded-full shrink-0"
          :class="task.enabled ? 'bg-success' : 'bg-neutral'"
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
    <div class="mt-4 p-3 rounded-lg bg-base-200">
      <div class="flex items-center justify-between mb-2">
        <span class="text-sm font-medium">
          {{ t("nav.routines") }}{{ t("panel.health.label") }}
        </span>
        <span
          class="text-sm font-bold"
          :class="
            healthScore >= 80 ? 'text-success' : healthScore >= 50 ? 'text-warning' : 'text-error'
          "
        >
          {{ healthScoreText }}
        </span>
      </div>
      <progress
        class="progress w-full"
        :class="
          healthScore >= 80
            ? 'progress-success'
            : healthScore >= 50
              ? 'progress-warning'
              : 'progress-error'
        "
        :value="healthScore"
        max="100"
      />
      <div class="flex justify-between text-xs opacity-60 mt-1">
        <span>{{ t("panel.health.running") }} {{ schedulerStore.enabledTasks.length }}</span>
        <span>{{ t("panel.health.total") }} {{ schedulerStore.tasks.length }}</span>
      </div>
    </div>

    <div class="flex gap-2">
      <RouterLink :to="{ name: 'routines' }" class="btn btn-outline btn-sm flex-1">
        <Icon icon="mdi:clock-plus" class="text-base" />
        {{ t("settings.scheduler.create") }}
      </RouterLink>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
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

const healthScoreText = computed(() => `${healthScore.value}%`)

function formatTriggerText(triggerConfig: TriggerConfig): string {
  return formatTrigger(t, locale.value, triggerConfig.type, triggerConfig)
}

function formatDateTimeText(dateStr?: string): string {
  return formatDateTime(t, locale.value, dateStr)
}
</script>
