<template>
  <div class="space-y-4 max-w-screen-xl mx-auto">
    <NCard :bordered="false" class="shadow-xl">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-base font-semibold flex items-center gap-2">
          <NIcon size="24" style="color: var(--primary-color)">
            <TimeOutline />
          </NIcon>
          {{ t("settings.scheduler.title") }}
        </h2>
        <NButton type="primary" @click="openCreateTaskDialog">
          <template #icon>
            <NIcon size="16"><AddOutline /></NIcon>
          </template>
          {{ t("settings.scheduler.create") }}
        </NButton>
      </div>

      <NTabs v-model:value="activeTab" type="segment" class="mb-4">
        <NTabPane name="tasks" :tab="t('settings.scheduler.taskList')">
          <SchedulerTaskList
            :tasks="schedulerStore.tasks"
            @toggle="handleToggleTask"
            @edit="openEditTaskDialog"
            @delete="handleDeleteTask"
          />
        </NTabPane>
        <NTabPane name="history" :tab="t('settings.scheduler.historyTitle')">
          <SchedulerExecutionHistory :executions="schedulerStore.executions" />
        </NTabPane>
      </NTabs>
    </NCard>

    <SchedulerTaskDialog
      v-model:show="showTaskDialog"
      :task="editingTask"
      @saved="handleTaskSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useI18n } from "vue-i18n"
import { AddOutline, TimeOutline } from "@vicons/ionicons5"
import SchedulerTaskDialog from "@/components/routines/dialogs/SchedulerTaskDialog.vue"
import SchedulerTaskList from "@/components/routines/SchedulerTaskList.vue"
import SchedulerExecutionHistory from "@/components/routines/SchedulerExecutionHistory.vue"
import { useSchedulerStore } from "@/stores"
import type { ScheduledTask } from "@/types/schedulerModel"

const { t } = useI18n()
const schedulerStore = useSchedulerStore()
const activeTab = ref<"tasks" | "history">("tasks")
const showTaskDialog = ref(false)
const editingTask = ref<ScheduledTask | null>(null)

onMounted(() => {
  void schedulerStore.fetchTasks()
  void schedulerStore.fetchExecutions()
})

function openCreateTaskDialog() {
  editingTask.value = null
  showTaskDialog.value = true
}

function openEditTaskDialog(task: ScheduledTask) {
  editingTask.value = task
  showTaskDialog.value = true
}

async function handleToggleTask(taskId: string, enabled: boolean) {
  await schedulerStore.toggleTask(taskId, enabled)
}

async function handleDeleteTask(taskId: string) {
  if (!confirm(t("settings.scheduler.deleteConfirm"))) {
    return
  }
  await schedulerStore.deleteTask(taskId)
}

function handleTaskSaved() {
  void schedulerStore.fetchTasks()
  void schedulerStore.fetchExecutions()
}
</script>
