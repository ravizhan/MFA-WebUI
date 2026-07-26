<template>
  <div class="space-y-4 max-w-screen-xl mx-auto">
    <div class="card bg-base-100 shadow-xl">
      <div class="card-body">
        <div class="flex items-center justify-between mb-4">
          <h2 class="card-title">
            <Icon icon="mdi:clock-outline" class="text-primary text-2xl" />
            {{ t("settings.scheduler.title") }}
          </h2>
          <div class="flex gap-2">
            <button class="btn btn-primary btn-sm" @click="openCreateTaskDialog">
              <Icon icon="mdi:plus" class="text-base" />
              {{ t("settings.scheduler.create") }}
            </button>
          </div>
        </div>

        <div class="tabs tabs-boxed mb-4">
          <a
            class="tab"
            :class="{ 'tab-active': activeTab === 'tasks' }"
            @click="activeTab = 'tasks'"
          >
            {{ t("settings.scheduler.taskList") }}
          </a>
          <a
            class="tab"
            :class="{ 'tab-active': activeTab === 'history' }"
            @click="activeTab = 'history'"
          >
            {{ t("settings.scheduler.execHistory") }}
          </a>
        </div>

        <div v-if="activeTab === 'tasks'">
          <SchedulerTaskList
            :tasks="schedulerStore.tasks"
            @toggle="handleToggleTask"
            @edit="openEditTaskDialog"
            @delete="handleDeleteTask"
          />
        </div>
        <div v-else>
          <SchedulerExecutionHistory :executions="schedulerStore.executions" />
        </div>
      </div>
    </div>

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
import { Icon } from "@iconify/vue"
import SchedulerTaskDialog from "@/components/settings/dialogs/SchedulerTaskDialog.vue"
import SchedulerTaskList from "@/components/settings/scheduler/SchedulerTaskList.vue"
import SchedulerExecutionHistory from "@/components/settings/scheduler/SchedulerExecutionHistory.vue"
import { useSchedulerStore } from "@/stores"
import { showGlobalMessage } from "@/services/feedback/message"
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
  const success = await schedulerStore.toggleTask(taskId, enabled)
  if (!success) {
    showGlobalMessage("error", schedulerStore.error || t("common.fail"))
  }
}

async function handleDeleteTask(taskId: string) {
  if (!confirm(t("settings.scheduler.deleteConfirm"))) {
    return
  }
  const success = await schedulerStore.deleteTask(taskId)
  if (!success) {
    showGlobalMessage("error", schedulerStore.error || t("common.fail"))
  }
}

function handleTaskSaved() {
  void schedulerStore.fetchExecutions()
}
</script>
