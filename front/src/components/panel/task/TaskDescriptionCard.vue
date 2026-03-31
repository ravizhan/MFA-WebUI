<template>
  <div class="col-name">{{ t("panel.taskDescription") }}</div>
  <n-card hoverable content-style="padding: 0.5rem 1rem;" class="transition-all duration-300">
    <MarkdownViewer :source="documentContent" :empty-text="t('panel.empty')" />
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import MarkdownViewer from "@/components/panel/common/MarkdownViewer.vue"
import { useIndexStore, useInterfaceStore } from "@/stores"
import type { Task } from "@/types/interface/model"
import { resolveInterfaceDocumentContent } from "@/utils/interface/content"

const { t, locale } = useI18n()
const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const documentContent = ref("")
const selectedTaskId = computed(() => indexStore.SelectedTaskID)

function getTaskDocumentSource(task: Task | null): string {
  if (!task) {
    return ""
  }
  if (task.description) {
    return task.description
  }
  if (typeof task.desc === "string") {
    return task.desc
  }
  if (Array.isArray(task.desc)) {
    return task.desc.join("\n\n")
  }
  if (typeof task.doc === "string") {
    return task.doc
  }
  if (Array.isArray(task.doc)) {
    return task.doc.join("\n\n")
  }
  return ""
}

watch(
  [selectedTaskId, () => locale.value, () => interfaceStore.interface],
  async () => {
    const task = interfaceStore.getTaskByEntry(selectedTaskId.value)
    documentContent.value = await resolveInterfaceDocumentContent(
      interfaceStore.interface,
      locale.value,
      getTaskDocumentSource(task),
    )
  },
  { immediate: true },
)
</script>
