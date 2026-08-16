<template>
  <div
    class="bg-base-100 rounded-lg overflow-hidden"
    :class="{ 'overflow-y-auto': maxHeight }"
    :style="maxHeight ? { maxHeight } : undefined"
  >
    <VueDraggable v-model="taskListData" :animation="150" ghost-class="ghost">
      <div
        v-for="(item, index) in taskListData"
        :key="item.id"
        class="flex items-center gap-3 px-3 py-2.5 border-b border-base-200 last:border-b-0 cursor-pointer transition-colors"
        :class="
          index % 2 === 0 ? 'bg-base-100 hover:bg-base-200' : 'bg-base-200/60 hover:bg-base-300/50'
        "
        @click="handleRowClick(item.id)"
      >
        <Icon
          icon="mdi:drag"
          class="text-base-content/40 cursor-grab active:cursor-grabbing text-lg shrink-0"
        />
        <input
          type="checkbox"
          class="checkbox checkbox-primary checkbox-sm shrink-0"
          :checked="isTaskSelected(item.id)"
          @click.stop
          @change="handleToggle(item.id, getChecked($event))"
        />
        <span class="flex-1 text-base truncate select-none">{{
          resolveTaskLabel(item.id, item.name)
        }}</span>
        <button
          class="btn btn-ghost btn-xs btn-circle shrink-0 w-7 h-7 min-h-0"
          @click.stop="handleConfig(item.id)"
        >
          <Icon icon="mdi:cog-outline" class="text-lg" />
        </button>
      </div>
    </VueDraggable>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"
import { useInterfaceStore } from "@/stores"
import type { TaskListItem } from "@/types/taskConfigModel"
import type { Task } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  tasks: TaskListItem[]
  selectedTasks: string[]
  controllerName?: string | null
  resourceName?: string | null
  hideIncompatible?: boolean
  maxHeight?: string
}

interface Emits {
  (e: "update:selected-tasks", value: string[]): void
  (e: "update:tasks", value: TaskListItem[]): void
  (e: "config", taskId: string): void
}

const {
  tasks,
  selectedTasks,
  controllerName = null,
  resourceName = null,
  hideIncompatible = false,
  maxHeight = "",
} = defineProps<Props>()

const emit = defineEmits<Emits>()
const { locale } = useI18n()
const interfaceStore = useInterfaceStore()

function isTaskVisible(taskId: string): boolean {
  if (!hideIncompatible) {
    return true
  }
  return interfaceStore.isTaskCompatibleByEntry(taskId, controllerName, resourceName)
}

const taskListData = computed({
  get: () => tasks.filter((task) => isTaskVisible(task.id)),
  set: (value: TaskListItem[]) => {
    if (!hideIncompatible) {
      emit("update:tasks", value)
      return
    }

    const visibleTaskIds = tasks.filter((task) => isTaskVisible(task.id)).map((task) => task.id)
    const visibleTaskIdSet = new Set(visibleTaskIds)

    const reorderedVisibleTaskIds = value.map((task) => task.id)
    const reorderedVisibleTaskIdSet = new Set(reorderedVisibleTaskIds)
    const taskById = new Map(tasks.map((task) => [task.id, task]))

    const orderedVisibleTasks: TaskListItem[] = []
    for (const taskId of reorderedVisibleTaskIds) {
      if (!visibleTaskIdSet.has(taskId)) {
        continue
      }
      const task = taskById.get(taskId)
      if (task) {
        orderedVisibleTasks.push(task)
      }
    }

    for (const taskId of visibleTaskIds) {
      if (reorderedVisibleTaskIdSet.has(taskId)) {
        continue
      }
      const task = taskById.get(taskId)
      if (task) {
        orderedVisibleTasks.push(task)
      }
    }

    let visibleCursor = 0
    const mergedTasks = tasks.map((task) => {
      if (!visibleTaskIdSet.has(task.id)) {
        return task
      }
      const visibleTask = orderedVisibleTasks[visibleCursor]
      visibleCursor += 1
      return visibleTask || task
    })

    emit("update:tasks", mergedTasks)
  },
})

function resolveTaskLabel(taskId: string, fallback: string) {
  const task = interfaceStore.getTaskByEntry(taskId)
  return resolveInterfaceText(interfaceStore.interface, locale.value, task?.label, fallback)
}

function isTaskSelected(taskId: string): boolean {
  return selectedTasks.includes(taskId)
}

function handleToggle(taskId: string, checked: boolean) {
  if (checked) {
    emit("update:selected-tasks", [...selectedTasks, taskId])
    return
  }
  emit(
    "update:selected-tasks",
    selectedTasks.filter((id) => id !== taskId),
  )
}

function handleConfig(taskId: string) {
  emit("config", taskId)
}

function getChecked(event: Event): boolean {
  const target = event.target
  if (target instanceof HTMLInputElement) return target.checked
  return false
}

function hasDocumentContent(task: Task): boolean {
  if (task.description) return true
  if (typeof task.desc === "string" && task.desc) return true
  if (Array.isArray(task.desc) && task.desc.length > 0) return true
  if (typeof task.doc === "string" && task.doc) return true
  if (Array.isArray(task.doc) && task.doc.length > 0) return true
  return false
}

function taskHasContent(task: Task | null): boolean {
  if (!task) return false
  const hasOptions = task.option && task.option.length > 0
  return hasOptions || hasDocumentContent(task)
}

function handleRowClick(taskId: string) {
  if (isTaskSelected(taskId)) {
    handleToggle(taskId, false)
    return
  }
  handleToggle(taskId, true)
  const task = interfaceStore.getTaskByEntry(taskId)
  if (taskHasContent(task)) {
    emit("config", taskId)
  }
}
</script>

<style scoped>
.cursor-grab {
  cursor: grab;
}
.cursor-grab:active {
  cursor: grabbing;
}
</style>
