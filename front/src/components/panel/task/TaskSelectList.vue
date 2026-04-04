<template>
  <n-list hoverable bordered>
    <template v-if="scrollable">
      <n-scrollbar trigger="none" class="max-h-75">
        <VueDraggable v-model="taskListData" :animation="150" ghost-class="ghost">
          <n-list-item
            v-for="item in taskListData"
            :key="item.id"
            class="cursor-grab active:cursor-grabbing"
          >
            <n-checkbox
              size="large"
              :label="resolveTaskLabel(item.id, item.name)"
              :checked="isTaskSelected(item.id)"
              @update:checked="(v: boolean) => handleToggle(item.id, v)"
            />
            <template #suffix>
              <n-button quaternary circle @click="handleConfig(item.id)">
                <template #icon>
                  <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
                </template>
              </n-button>
            </template>
          </n-list-item>
        </VueDraggable>
      </n-scrollbar>
    </template>
    <template v-else>
      <VueDraggable v-model="taskListData" :animation="150" ghost-class="ghost">
        <n-list-item
          v-for="item in taskListData"
          :key="item.id"
          class="cursor-grab active:cursor-grabbing"
        >
          <n-checkbox
            size="large"
            :label="resolveTaskLabel(item.id, item.name)"
            :checked="isTaskSelected(item.id)"
            @update:checked="(v: boolean) => handleToggle(item.id, v)"
          />
          <template #suffix>
            <n-button quaternary circle @click="handleConfig(item.id)">
              <template #icon>
                <n-icon><div class="i-mdi-cog-outline"></div></n-icon>
              </template>
            </n-button>
          </template>
        </n-list-item>
      </VueDraggable>
    </template>
  </n-list>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "@/stores"
import type { TaskListItem } from "@/types/task-config/model"
import { resolveInterfaceText } from "@/utils/interface/content"

interface Props {
  tasks: TaskListItem[]
  selectedTasks: string[]
  scrollable?: boolean
}

interface Emits {
  (e: "update:selectedTasks", value: string[]): void
  (e: "update:tasks", value: TaskListItem[]): void
  (e: "config", taskId: string): void
}

const props = withDefaults(defineProps<Props>(), {
  scrollable: false,
})

const emit = defineEmits<Emits>()
const { locale } = useI18n()
const interfaceStore = useInterfaceStore()

const taskListData = computed({
  get: () => props.tasks,
  set: (value: TaskListItem[]) => emit("update:tasks", value),
})

function resolveTaskLabel(taskId: string, fallback: string) {
  const task = interfaceStore.getTaskByEntry(taskId)
  return resolveInterfaceText(interfaceStore.interface, locale.value, task?.label, fallback)
}

function isTaskSelected(taskId: string): boolean {
  return props.selectedTasks.includes(taskId)
}

function handleToggle(taskId: string, checked: boolean) {
  let newSelected: string[]
  if (checked) {
    newSelected = [...props.selectedTasks, taskId]
  } else {
    newSelected = props.selectedTasks.filter((id) => id !== taskId)
  }
  emit("update:selectedTasks", newSelected)
}

function handleConfig(taskId: string) {
  emit("config", taskId)
}
</script>

<style scoped>
.cursor-grab {
  cursor: grab;
}

.cursor-grab:active {
  cursor: grabbing;
}

.ghost {
  opacity: 0.5;
  background: #c8ebfb;
}
</style>
