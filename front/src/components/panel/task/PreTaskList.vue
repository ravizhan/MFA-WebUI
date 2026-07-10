<template>
  <div class="card bg-base-100 shadow-sm border border-base-300" :class="{ 'mb-2': !embedded }">
    <div class="collapse collapse-arrow bg-transparent">
      <input
        :id="`pre-task-${embedded ? 'embedded' : 'standalone'}`"
        type="checkbox"
        :checked="expanded"
        @change="handleExpandedChange($event)"
      />
      <div class="collapse-title text-base font-medium py-2 px-3 min-h-0 flex items-center gap-2">
        <Icon icon="mdi:playlist-play" class="text-primary text-2xl" />
        {{ $t("taskConfig.preTasks.title") }}
      </div>
      <div class="collapse-content px-3">
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm opacity-60">{{ $t("taskConfig.preTasks.description") }}</span>
          <button class="btn btn-primary btn-sm" @click="handleAdd">
            <Icon icon="mdi:plus" class="text-base" />
            {{ $t("taskConfig.preTasks.add") }}
          </button>
        </div>

        <div v-if="preTasks.length > 0" class="space-y-1.5">
          <VueDraggable
            v-model="preTasks"
            :animation="150"
            handle=".pre-task-drag-handle"
            ghost-class="ghost"
          >
            <div
              v-for="(item, index) in preTasks"
              :key="item.id"
              class="flex items-center gap-2 p-2 bg-base-200/70 rounded-lg border border-base-300/50"
            >
              <div class="pre-task-drag-handle cursor-grab text-base-content/40">
                <Icon icon="mdi:drag" class="text-lg" />
              </div>
              <input
                v-model="item.command"
                type="text"
                class="input input-bordered input-sm flex-1"
                :placeholder="$t('taskConfig.preTasks.command')"
              />
              <input
                v-model.number="item.timeout"
                type="number"
                class="input input-bordered input-sm w-16"
                min="1"
                max="3600"
              />
              <input
                type="checkbox"
                class="toggle toggle-primary toggle-md"
                :checked="item.enabled"
                @change="item.enabled = getChecked($event)"
              />
              <button
                class="btn btn-ghost btn-circle btn-xs text-error"
                @click="handleDelete(index)"
              >
                <Icon icon="mdi:delete" class="text-xl" />
              </button>
            </div>
          </VueDraggable>
        </div>

        <div v-else class="text-center py-4 opacity-50 bg-base-200/50 rounded-lg">
          <Icon icon="mdi:inbox" class="text-3xl mx-auto mb-1" />
          <p class="text-sm">{{ $t("taskConfig.preTasks.empty") }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import { Icon } from "@iconify/vue"
import type { PreTaskCommand } from "@/types/taskConfigModel"

interface Props {
  embedded?: boolean
}

const { embedded = false } = defineProps<Props>()

const modelValue = defineModel<PreTaskCommand[]>()

const expanded = ref(embedded)

const preTasks = computed<PreTaskCommand[]>({
  get: () => modelValue.value || [],
  set: (value) => (modelValue.value = value),
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

function handleExpandedChange(event: Event) {
  expanded.value = getChecked(event)
}

function getChecked(event: Event): boolean {
  const target = event.target
  if (target instanceof HTMLInputElement) return target.checked
  return false
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
  background: oklch(85% 0.1 200);
}
</style>
