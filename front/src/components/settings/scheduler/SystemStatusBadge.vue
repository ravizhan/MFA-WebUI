<template>
  <span v-if="badgeType === 'active'" class="badge badge-soft badge-success">
    {{
      scope === "system"
        ? t("settings.scheduler.status.systemSystem")
        : t("settings.scheduler.status.systemUser")
    }}
  </span>
  <span v-else-if="badgeType === 'orphaned'" class="badge badge-dash badge-warning gap-1">
    {{ t("settings.scheduler.dialog.orphaned") }}
    <button class="btn btn-ghost btn-xs p-0 h-auto min-h-0" @click="emit('repair')">
      {{ t("settings.scheduler.dialog.repair") }}
    </button>
  </span>
  <span v-else-if="badgeType === 'error'" class="badge badge-dash badge-error">
    {{ t("settings.scheduler.status.needsRepair") }}
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
  if (status.state === "active" && !status.orphaned) return "active"
  if (status.orphaned) return "orphaned"
  if (status.state === "error" || status.state === "pending_cleanup") return "error"
  return null
})

const scope = computed(() => status?.scope)
</script>
