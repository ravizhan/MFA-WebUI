<template>
  <NEmpty
    v-if="executions.length === 0"
    size="small"
    :description="t('settings.scheduler.noHistory')"
    class="py-6"
  >
    <template #icon>
      <NIcon size="30"><FileTrayOutline /></NIcon>
    </template>
  </NEmpty>
  <div v-else class="space-y-3">
    <SchedulerExecutionRow v-for="exec in executions" :key="exec.id" :execution="exec" />
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NEmpty, NIcon } from "naive-ui"
import { FileTrayOutline } from "@vicons/ionicons5"
import type { TaskExecution } from "@/types/schedulerModel"
import SchedulerExecutionRow from "./SchedulerExecutionRow.vue"

const { executions } = defineProps<{
  executions: TaskExecution[]
}>()

const { t } = useI18n()
</script>
