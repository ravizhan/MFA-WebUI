<template>
  <div class="task-option-panel">
    <div v-if="showHeader && currentTaskName" class="text-center mb-2">
      <span class="badge badge-primary badge-lg"> {{ headerLabel }}{{ currentTaskName }} </span>
    </div>

    <div :class="scrollbarClass">
      <div v-if="!currentTaskId" class="text-center py-8 opacity-50">
        <Icon icon="mdi:cog-off" class="text-3xl mx-auto mb-2" />
        <p>{{ emptyText }}</p>
      </div>
      <div v-else>
        <div v-if="taskOptions.length > 0" class="bg-base-200 rounded-lg overflow-hidden">
          <OptionItem
            v-for="optName in taskOptions"
            :key="optName"
            :name="optName"
            :task-options="currentTaskOptions"
          />
        </div>
        <div v-else class="text-center py-8 opacity-50">
          <Icon icon="mdi:inbox" class="text-3xl mx-auto mb-2" />
          <p>{{ noOptionsText }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { useInterfaceStore } from "@/stores"
import type { TaskOptionsByTask } from "@/types/schedulerModel"
import OptionItem from "@/components/panel/task/OptionItem.vue"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  currentTaskId: string | null
  options: TaskOptionsByTask
  showHeader?: boolean
  headerLabel?: string
  emptyText?: string
  noOptionsText?: string
  scrollbarClass?: string
}

const {
  currentTaskId,
  options,
  showHeader = false,
  headerLabel = "",
  emptyText = "",
  noOptionsText = "",
  scrollbarClass = "max-h-65 overflow-y-auto rounded-xl",
} = defineProps<Props>()

const interfaceStore = useInterfaceStore()
const { locale } = useI18n()

const taskOptionsMap = ref<TaskOptionsByTask>({})
watch(
  () => options,
  (newOptions) => {
    taskOptionsMap.value = newOptions
  },
  { immediate: true },
)

const currentTaskName = computed(() => {
  if (!currentTaskId) return ""
  const task = interfaceStore.getTaskByEntry(currentTaskId)
  return resolveInterfaceText(interfaceStore.interface, locale.value, task?.label, task?.name || "")
})

const currentTaskOptions = computed(() => {
  if (!currentTaskId) {
    return {}
  }
  return taskOptionsMap.value[currentTaskId] || {}
})

watch(
  () => currentTaskId,
  (taskId) => {
    if (taskId && !taskOptionsMap.value[taskId]) {
      taskOptionsMap.value[taskId] = {}
    }
  },
  { immediate: true },
)

const taskOptions = computed(() => {
  if (!currentTaskId) return []
  const task = interfaceStore.getTaskByEntry(currentTaskId)
  return task?.option || []
})
</script>

<style scoped>
.task-option-panel {
  min-height: 50px;
}
</style>
