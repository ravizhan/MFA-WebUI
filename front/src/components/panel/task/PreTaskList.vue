<template>
  <NCard size="small" content-style="padding: 0">
    <NCollapse v-model:expanded-names="expandedNames" arrow-placement="right">
      <NCollapseItem name="pre-tasks">
        <template #header>
          <PreTaskHeader />
        </template>
        <div class="px-3 pb-3 space-y-2">
          <PreTaskToolbar @add="handleAdd" />

          <VueDraggable
            v-if="preTasks.length > 0"
            v-model="preTasks"
            class="space-y-1.5"
            :animation="150"
            handle=".pre-task-drag-handle"
            :delay="120"
            :delay-on-touch-only="true"
            ghost-class="ghost"
          >
            <PreTaskRow
              v-for="(item, index) in preTasks"
              :key="item.id"
              :item="item"
              @delete="handleDelete(index)"
            />
          </VueDraggable>

          <NEl
            v-else
            tag="div"
            class="text-center py-4 opacity-50 rounded-lg"
            style="background: var(--card-color)"
          >
            <NIcon size="30" class="mx-auto mb-1"><FileTrayOutline /></NIcon>
            <p class="text-sm">{{ $t("taskConfig.preTasks.empty") }}</p>
          </NEl>
        </div>
      </NCollapseItem>
    </NCollapse>
  </NCard>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { VueDraggable } from "vue-draggable-plus"
import { FileTrayOutline } from "@vicons/ionicons5"
import type { PreTaskCommand } from "@/types/taskConfigModel"
import PreTaskHeader from "@/components/panel/task/PreTaskHeader.vue"
import PreTaskRow from "@/components/panel/task/PreTaskRow.vue"
import PreTaskToolbar from "@/components/panel/task/PreTaskToolbar.vue"

interface Props {
  embedded?: boolean
}

const { embedded = false } = defineProps<Props>()

const modelValue = defineModel<PreTaskCommand[]>()

const expanded = ref(embedded)
const expandedNames = computed<string[]>({
  get: () => (expanded.value ? ["pre-tasks"] : []),
  set: (names) => {
    expanded.value = names.includes("pre-tasks")
  },
})

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
</script>
