<template>
  <span v-if="badgeType === 'active'" class="badge badge-soft badge-success">
    {{ t("settings.scheduler.status.systemUser") }}
  </span>
  <span v-else-if="badgeType === 'error'" class="badge badge-dash badge-error gap-1">
    {{ t("settings.scheduler.status.needsRepair") }}
    <button class="btn btn-ghost btn-xs p-0 h-auto min-h-0" @click="emit('repair')">
      {{ t("settings.scheduler.dialog.repair") }}
    </button>
  </span>
  <span v-else-if="badgeType === 'disabled'" class="badge badge-soft opacity-60">
    {{ t("settings.scheduler.status.stopped") }}
  </span>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import type { SystemTaskStatus } from "@/types/schedulerModel"

const { status } = defineProps<{
  status?: SystemTaskStatus
}>()

const emit = defineEmits<{
  (e: "repair"): void
}>()

const { t } = useI18n()

const badgeType = computed(() => {
  if (!status) return null
  if (status.state === "error") return "error"
  if (status.registered && status.path_valid === false) return "error"
  if (status.state === "active" && status.registered) return "active"
  if (status.enabled === false || status.registered === false) return "disabled"
  return null
})
</script>
