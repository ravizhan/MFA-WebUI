<template>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-start max-w-7xl mx-auto">
    <!-- Left: Task list with start/stop -->
    <NCard
      :bordered="false"
      content-style="display: flex; flex-direction: column; padding-bottom: 0"
    >
      <template #header>
        <h2 class="text-base mb-3 shrink-0 flex items-center gap-2">
          <NIcon size="24">
            <ListOutline />
          </NIcon>
          {{ t("panel.taskList") }}
        </h2>
      </template>
      <PreTaskList v-model="configStore.preTasks" class="mb-2" />
      <NCard size="small" content-style="padding: 0">
        <TaskSelectList
          class="mt-3 task-list-scroll"
          :tasks="configStore.taskList"
          :selected-tasks="selectedTaskIds"
          :controller-name="deviceStore.selectedControllerName"
          :resource-name="deviceStore.resource"
          :hide-incompatible="true"
          @update:tasks="handleTasksUpdate"
          @update:selected-tasks="handleSelectedTasksUpdate"
          @config="handleConfigTask"
        />
      </NCard>
      <div class="flex justify-center gap-2 pt-4 shrink-0">
        <NButton
          type="primary"
          class="min-w-32"
          :disabled="indexStore.TaskRunning"
          @click="handleStart"
        >
          <template #icon>
            <NIcon><PlayOutline /></NIcon>
          </template>
          {{ t("panel.start") }}
        </NButton>
        <NButton
          type="warning"
          class="min-w-32"
          :disabled="!indexStore.TaskRunning"
          @click="handleStop"
        >
          <template #icon>
            <NIcon><StopOutline /></NIcon>
          </template>
          {{ t("panel.stop") }}
        </NButton>
      </div>
      <div class="text-center shrink-0 py-2">
        <NButton quaternary size="small" type="warning" @click="deviceStore.resetConfig()">
          {{ t("panel.resetConfig") }}
        </NButton>
      </div>
    </NCard>

    <!-- Right: Task Options + Description (desktop only) -->
    <NCard
      :bordered="false"
      class="task-settings-card"
      content-style="display: flex; flex-direction: column"
    >
      <PanelTaskColumn />
    </NCard>

    <!-- Mobile task settings drawer -->
    <TaskSettingsDrawer v-if="isMobile" />
  </div>

  <StartConflictDialog />
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue"
import { useI18n } from "vue-i18n"
import { useRouter } from "vue-router"
import { NButton, NCard, NIcon } from "naive-ui"
import { ListOutline, PlayOutline, StopOutline } from "@vicons/ionicons5"
import PanelTaskColumn from "@/components/panel/PanelTaskColumn.vue"
import TaskSettingsDrawer from "@/components/panel/task/TaskSettingsDrawer.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import StartConflictDialog from "@/components/tasks/StartConflictDialog.vue"
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
