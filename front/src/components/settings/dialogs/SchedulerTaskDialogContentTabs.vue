<template>
  <div class="flex min-h-0 flex-col gap-3">
    <NTabs
      v-model:value="activeTab"
      type="segment"
      size="small"
      class="w-full flex-nowrap overflow-x-auto"
    >
      <NTabPane name="pre-tasks">
        <template #tab>
          <span class="flex items-center gap-1.5 whitespace-nowrap">
            <NIcon size="16"><TerminalOutline /></NIcon>
            {{ t("settings.scheduler.dialog.tab.preTasks") }}
          </span>
        </template>
        <div class="min-h-48">
          <PreTaskList v-model="preTasks" embedded />
        </div>
      </NTabPane>
      <NTabPane name="task-list">
        <template #tab>
          <span class="flex items-center gap-1.5 whitespace-nowrap">
            <NIcon size="16"><ListOutline /></NIcon>
            {{ t("settings.scheduler.dialog.tab.taskList") }}
          </span>
        </template>
        <div class="min-h-48">
          <TaskSelectList
            :tasks="taskListData"
            :selected-tasks="selectedTasks"
            :controller-name="controllerName"
            :resource-name="resourceName"
            :hide-incompatible="true"
            max-height="20rem"
            @update:tasks="emit('update:tasks', $event)"
            @update:selected-tasks="emit('update:selected-tasks', $event)"
            @config="emit('config', $event)"
          />
        </div>
      </NTabPane>
      <NTabPane name="task-settings">
        <template #tab>
          <span class="flex items-center gap-1.5 whitespace-nowrap">
            <NIcon size="16"><OptionsOutline /></NIcon>
            {{ t("settings.scheduler.dialog.tab.taskSettings") }}
          </span>
        </template>
        <div class="min-h-48">
          <TaskOptionPanel
            :current-task-id="currentSettingTaskId"
            :options="taskOptions"
            :show-header="true"
            :header-label="t('settings.scheduler.dialog.currentSetting')"
            :empty-text="t('settings.scheduler.dialog.selectTaskTip')"
            :no-options-text="t('settings.scheduler.dialog.noOptions')"
          />
        </div>
      </NTabPane>
    </NTabs>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { NIcon, NTabPane, NTabs } from "naive-ui"
import { ListOutline, OptionsOutline, TerminalOutline } from "@vicons/ionicons5"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import TaskOptionPanel from "@/components/panel/task/TaskOptionPanel.vue"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import type { PreTaskCommand, TaskListItem } from "@/types/taskConfigModel"
import type { TaskOptionsByTask } from "@/types/schedulerModel"

type ActiveTab = "task-list" | "task-settings" | "pre-tasks"

interface Props {
  taskListData: TaskListItem[]
  selectedTasks: string[]
  controllerName?: string | null
  resourceName?: string | null
  taskOptions: TaskOptionsByTask
  currentSettingTaskId: string | null
}

const {
  taskListData,
  selectedTasks,
  controllerName,
  resourceName,
  taskOptions,
  currentSettingTaskId,
} = defineProps<Props>()

const activeTab = defineModel<ActiveTab>("activeTab", { required: true })
const preTasks = defineModel<PreTaskCommand[]>("preTasks", { required: true })

const emit = defineEmits<{
  (e: "update:tasks", value: TaskListItem[]): void
  (e: "update:selected-tasks", value: string[]): void
  (e: "config", taskId: string): void
}>()

const { t } = useI18n()
</script>
