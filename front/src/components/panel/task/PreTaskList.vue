<template>
  <n-card hoverable>
    <template #header>
      <div class="flex items-start justify-between gap-4">
        <div class="flex flex-col gap-1">
          <span class="font-semibold">{{ $t("taskConfig.preTasks.title") }}</span>
          <span class="text-sm text-gray-500">{{ $t("taskConfig.preTasks.description") }}</span>
        </div>
        <n-button secondary type="info" size="small" @click="handleAdd">
          <template #icon>
            <n-icon><div class="i-mdi-plus" /></n-icon>
          </template>
          {{ $t("taskConfig.preTasks.add") }}
        </n-button>
      </div>
    </template>

    <n-list v-if="preTasks.length > 0" hoverable bordered>
      <VueDraggable
        v-model="preTasks"
        :animation="150"
        handle=".pre-task-drag-handle"
        ghost-class="ghost"
      >
        <n-list-item v-for="item in preTasks" :key="item.id" class="pre-task-row">
          <div class="flex w-full items-center gap-2">
            <div class="pre-task-drag-handle cursor-grab text-gray-400">
              <n-icon><div class="i-mdi-drag" /></n-icon>
            </div>
            <n-input
              v-model:value="item.command"
              class="flex-1"
              :placeholder="$t('taskConfig.preTasks.command')"
              clearable
            />
            <n-input-number
              v-model:value="item.timeout"
              class="w-28"
              :min="1"
              :max="3600"
              :show-button="true"
              size="small"
            />
            <n-switch v-model:value="item.enabled" :round="false" />
            <n-button quaternary circle type="error" size="small" @click="handleDelete(index)">
              <template #icon>
                <n-icon><div class="i-mdi-delete" /></n-icon>
              </template>
            </n-button>
          </div>
        </n-list-item>
      </VueDraggable>
    </n-list>

    <n-empty v-else :description="$t('taskConfig.preTasks.empty')" />
  </n-card>
</template>

<script setup lang="ts">
import { storeToRefs } from "pinia"
import { VueDraggable } from "vue-draggable-plus"
import { useTaskConfigStore } from "@/stores"

const taskConfigStore = useTaskConfigStore()
const { preTasks } = storeToRefs(taskConfigStore)

function handleAdd() {
  preTasks.value.push({
    id: crypto.randomUUID(),
    command: "",
    enabled: true,
    timeout: 30,
  })
}

function handleDelete(index: number) {
  preTasks.value.splice(index, 1)
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

.pre-task-row :deep(.n-list-item__main) {
  width: 100%;
}
</style>
