<template>
  <n-card :hoverable="!embedded" class="pre-task-card" content-style="padding: 0.5rem 1rem;">
    <n-collapse
      v-model:expanded-names="expandedNames"
      arrow-placement="right"
      class="pre-task-collapse"
    >
      <n-collapse-item
        name="preTask"
        display-directive="show"
        :title="$t('taskConfig.preTasks.title')"
      >
        <div
          style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
          "
        >
          <span class="text-sm text-gray-500">{{ $t("taskConfig.preTasks.description") }}</span>
          <n-button secondary type="info" size="small" @click="handleAdd">
            <template #icon>
              <n-icon><div class="i-mdi-plus" /></n-icon>
            </template>
            {{ $t("taskConfig.preTasks.add") }}
          </n-button>
        </div>

        <n-list v-if="preTasks.length > 0" hoverable bordered>
          <VueDraggable
            v-model="preTasks"
            :animation="150"
            handle=".pre-task-drag-handle"
            ghost-class="ghost"
          >
            <n-list-item v-for="(item, index) in preTasks" :key="item.id" class="pre-task-row">
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
                  class="w-20"
                  :min="1"
                  :max="3600"
                  :show-button="true"
                  size="medium"
                  button-placement="both"
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
      </n-collapse-item>
    </n-collapse>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import type { PreTaskCommand } from "@/types/task-config/model"

interface Props {
  modelValue: PreTaskCommand[]
  embedded?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  embedded: false,
})

const emit = defineEmits<{
  (e: "update:modelValue", value: PreTaskCommand[]): void
}>()

const expandedNames = ref<Array<string | number>>(props.embedded ? ["preTask"] : [])

const preTasks = computed<PreTaskCommand[]>({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
})

function handleAdd() {
  preTasks.value = [
    ...preTasks.value,
    {
      id: crypto.randomUUID(),
      command: "",
      enabled: true,
      timeout: 30,
    },
  ]
}

function handleDelete(index: number) {
  preTasks.value = preTasks.value.filter((_, i) => i !== index)
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

.pre-task-card {
  margin: 0 0 0.5rem 0;
  overflow: hidden;
}

.pre-task-row {
  padding: 5px 5px !important;
}

.pre-task-row :deep(.n-list-item__main) {
  width: 100%;
}

.pre-task-collapse :deep(.n-collapse-item) {
  margin-left: 0;
  border-top: none;
}

.pre-task-collapse :deep(.n-collapse-item__header) {
  min-height: 2.5rem;
}

.pre-task-collapse :deep(.n-collapse-item__content-wrapper) {
  overflow: hidden;
}

.pre-task-collapse :deep(.n-collapse-item__content-inner) {
  padding-top: 0 !important;
  padding-bottom: 0.5rem;
}

:deep(.n-collapse-item__header-main) {
  justify-content: space-between;
}
</style>
