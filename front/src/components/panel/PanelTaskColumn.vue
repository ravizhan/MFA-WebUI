<template>
  <div class="col-name">{{ t("panel.taskSettings") }}</div>
  <n-card hoverable content-style="padding: 0;" class="transition-all duration-300 overflow-hidden">
    <TaskOptionPanel
      :current-task-id="selectedTaskId"
      :options="configStore.options"
      :scrollbar-class="scrollbarClass"
    />
  </n-card>
  <TaskDescriptionCard />
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import TaskDescriptionCard from "@/components/panel/task/TaskDescriptionCard.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import { useIndexStore, useTaskConfigStore } from "@/stores"

const { t } = useI18n()
const indexStore = useIndexStore()
const configStore = useTaskConfigStore()
const scrollbarClass = "max-h-65 !rounded-[12px]"
const selectedTaskId = computed(() => indexStore.SelectedTaskID)
</script>
