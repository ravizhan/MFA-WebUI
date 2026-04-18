<template>
  <div class="task-option-panel">
    <!-- 当前配置任务提示（可选显示） -->
    <div v-if="showHeader && currentTaskName" class="text-center mb-2">
      <n-tag type="info" size="large"> {{ headerLabel }}{{ currentTaskName }} </n-tag>
    </div>

    <!-- 选项列表 -->
    <n-scrollbar trigger="none" :class="scrollbarClass">
      <div v-if="!currentTaskId">
        <n-empty :description="emptyText" />
      </div>
      <div v-else>
        <n-list v-if="taskOptions.length > 0" hoverable>
          <OptionItem
            v-for="optName in taskOptions"
            :key="optName"
            :name="optName"
            :task-options="currentTaskOptions"
          />
        </n-list>
        <n-empty v-else :description="noOptionsText" />
      </div>
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "@/stores"
import type { TaskOptionsByTask } from "@/types/scheduler/model"
import OptionItem from "@/components/panel/task/OptionItem.vue"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  /** 当前配置的任务ID */
  currentTaskId: string | null
  /** 选项数据 */
  options: TaskOptionsByTask
  /** 是否显示头部 */
  showHeader?: boolean
  /** 头部标签前缀 */
  headerLabel?: string
  /** 空状态提示文本 */
  emptyText?: string
  /** 无选项提示文本 */
  noOptionsText?: string
  /** 滚动区域 class */
  scrollbarClass?: string
}

const props = withDefaults(defineProps<Props>(), {
  showHeader: false,
  headerLabel: "",
  emptyText: "",
  noOptionsText: "",
  scrollbarClass: "max-h-65 !rounded-[12px]",
})

const interfaceStore = useInterfaceStore()
const { locale } = useI18n()

const currentTaskName = computed(() => {
  if (!props.currentTaskId) return ""
  const task = interfaceStore.getTaskByEntry(props.currentTaskId)
  return resolveInterfaceText(interfaceStore.interface, locale.value, task?.label, task?.name || "")
})

const currentTaskOptions = computed(() => {
  if (!props.currentTaskId) {
    return {}
  }
  return props.options[props.currentTaskId] || {}
})

const taskOptions = computed(() => {
  if (!props.currentTaskId) return []
  const task = interfaceStore.getTaskByEntry(props.currentTaskId)
  return task?.option || []
})
</script>

<style scoped>
.task-option-panel {
  min-height: 50px;
}
</style>
