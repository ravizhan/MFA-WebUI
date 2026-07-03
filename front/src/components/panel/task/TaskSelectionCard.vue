<template>
  <div class="col-name">{{ t("panel.taskList") }}</div>
  <n-card hoverable>
    <PreTaskList v-model="configStore.preTasks" />
    <TaskSelectList
      :tasks="tasks"
      :selected-tasks="selectedTaskIds"
      :scrollable="scrollShow"
      :controller-name="controllerName"
      :resource-name="resourceName"
      :hide-incompatible="hideIncompatible"
      @update:tasks="(value: any) => emit('update:tasks', value)"
      @update:selected-tasks="(value: any) => emit('update:selected-tasks', value)"
      @config="(taskId: any) => emit('config', taskId)"
    />
    <n-flex class="form-btn" justify="center" :wrap="true" :size="[12, 12]">
      <n-button
        class="min-w-[9rem]"
        strong
        secondary
        type="info"
        size="large"
        @click="emit('start')"
        >{{ t("panel.start") }}</n-button
      >
      <n-button
        class="min-w-[9rem]"
        strong
        secondary
        type="info"
        size="large"
        @click="emit('stop')"
        >{{ t("panel.stop") }}</n-button
      >
    </n-flex>
    <n-flex class="form-btn" justify="center">
      <n-button quaternary type="warning" size="small" @click="emit('reset')">{{
        t("panel.resetConfig")
      }}</n-button>
    </n-flex>
  </n-card>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { useTaskConfigStore } from "@/stores"
import PreTaskList from "@/components/panel/task/PreTaskList.vue"
import TaskSelectList from "@/components/panel/task/TaskSelectList.vue"
import type { TaskListItem } from "@/types/task-config/model"

defineProps<{
  tasks: TaskListItem[]
  selectedTaskIds: string[]
  scrollShow: boolean
  controllerName?: string | null
  resourceName?: string | null
  hideIncompatible?: boolean
}>()

const emit = defineEmits<{
  (e: "update:tasks", value: TaskListItem[]): void
  (e: "update:selected-tasks", value: string[]): void
  (e: "config", taskId: string): void
  (e: "start"): void
  (e: "stop"): void
  (e: "reset"): void
}>()

const { t } = useI18n()
const configStore = useTaskConfigStore()
</script>

<style scoped>
.form-btn {
  text-align: center;
  padding-top: 5%;
}
</style>
