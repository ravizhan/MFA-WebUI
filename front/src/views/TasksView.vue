<template>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-start max-w-screen-xl mx-auto">
    <!-- Left: Task list with start/stop -->
    <div class="card bg-base-100 shadow-xl">
      <div class="card-body flex flex-col">
        <h2 class="card-title text-base mb-3 shrink-0">
          <Icon icon="mdi:format-list-checks" class="text-primary text-2xl" />
          {{ t("panel.taskList") }}
        </h2>
        <PreTaskList v-model="configStore.preTasks" />
        <div class="mt-3 task-list-scroll rounded-lg border border-base-300">
          <TaskSelectList
            :tasks="configStore.taskList"
            :selected-tasks="selectedTaskIds"
            :controller-name="deviceStore.selectedControllerName"
            :resource-name="deviceStore.resource"
            :hide-incompatible="true"
            @update:tasks="handleTasksUpdate"
            @update:selected-tasks="handleSelectedTasksUpdate"
            @config="handleConfigTask"
          />
        </div>
        <div class="flex justify-center gap-2 pt-3 shrink-0">
          <button
            class="btn btn-primary min-w-[8rem]"
            :disabled="indexStore.TaskRunning"
            @click="handleStart"
          >
            <Icon icon="mdi:play" />
            {{ t("panel.start") }}
          </button>
          <button
            class="btn btn-secondary min-w-[8rem]"
            :disabled="!indexStore.TaskRunning"
            @click="handleStop"
          >
            <Icon icon="mdi:stop" />
            {{ t("panel.stop") }}
          </button>
        </div>
        <div class="text-center shrink-0">
          <button class="btn btn-ghost btn-sm text-warning" @click="deviceStore.resetConfig()">
            {{ t("panel.resetConfig") }}
          </button>
        </div>
      </div>
    </div>

    <!-- Right: Task Options + Description (desktop only) -->
    <div class="card bg-base-100 shadow-xl task-settings-card">
      <div class="card-body">
        <PanelTaskColumn />
      </div>
    </div>

    <!-- Mobile task settings drawer -->
    <TaskSettingsDrawer v-if="isMobile" />
  </div>

  <StartConflictDialog />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { Icon } from "@iconify/vue"
import PanelTaskColumn from "@/components/panel/PanelTaskColumn.vue"
import TaskSettingsDrawer from "@/components/panel/task/TaskSettingsDrawer.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import StartConflictDialog from "@/components/settings/scheduler/StartConflictDialog.vue"
import { stopTask } from "@/services/api"
import { useIndexStore, useTaskConfigStore, useDeviceConnectionStore } from "@/stores"
import type { TaskListItem } from "@/types/taskConfigModel"
import { useViewport } from "@/utils/viewport/useViewport"

const { t } = useI18n()
const router = useRouter()
const indexStore = useIndexStore()
const configStore = useTaskConfigStore()
const deviceStore = useDeviceConnectionStore()
const { isMobile } = useViewport()

const selectedTaskIds = computed(() =>
  configStore.taskList.filter((task) => task.checked).map((task) => task.id),
)

function handleTasksUpdate(tasks: TaskListItem[]) {
  configStore.taskList = tasks
}

function handleSelectedTasksUpdate(selectedIds: string[]) {
  configStore.taskList = configStore.taskList.map((task) => ({
    ...task,
    checked: selectedIds.includes(task.id),
  }))
}

function handleConfigTask(taskId: string) {
  indexStore.SelectTask(taskId)
  if (isMobile.value) {
    indexStore.openTaskSettingsDrawer(taskId)
  }
}

async function handleStart() {
  const success = await deviceStore.StartTask()
  if (success) {
    router.push({ name: "logs" })
  }
}

async function handleStop() {
  // Await stop API; leave TaskRunning true until SSE task.failed/completed clears it
  await stopTask()
}

onMounted(() => {
  deviceStore.init()
})

onUnmounted(() => {
  deviceStore.cleanup()
})
</script>

<style scoped>
.task-list-scroll {
  max-height: calc(100vh - 22rem);
  overflow-y: auto;
}
.task-settings-card {
  display: none;
}
@media (min-width: 1024px) {
  .task-list-scroll {
    max-height: calc(100vh - 24rem);
  }
  .task-settings-card {
    display: block;
  }
}
@media (max-width: 1023px) {
  .task-list-scroll {
    max-height: none;
    overflow-y: visible;
  }
}
</style>
