<template>
  <div class="col-name">{{ t("panel.taskDescription") }}</div>
  <n-card hoverable content-style="padding: 0.5rem 1rem;" class="transition-all duration-300">
    <n-scrollbar trigger="none">
      <div ref="mdContainer" class="markdown-body min-h-50 max-h-65" v-html="md"></div>
    </n-scrollbar>
  </n-card>
  <n-image ref="previewImageRef" :src="previewSrc" :show-toolbar="true" style="display: none" />
</template>

<script setup lang="ts">
import DOMPurify from "dompurify"
import { marked } from "marked"
import type { Tokens } from "marked"
import { NImage } from "naive-ui"
import { computed, nextTick, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { useIndexStore, useInterfaceStore } from "@/stores"

const { t } = useI18n()
const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const md = ref("")
const mdContainer = ref<HTMLElement | null>(null)
const previewImageRef = ref<InstanceType<typeof NImage> | null>(null)
const previewSrc = ref("")
const render = new marked.Renderer()

render.image = function ({ href, title, text }: Tokens.Image) {
  const safeHref = href || ""
  const titleAttr = title ? ` title="${title}"` : ""
  const altAttr = text ? ` alt="${text}"` : ""
  return `<img src="${safeHref}"${titleAttr}${altAttr} class="preview-image" style="max-width: 100%; object-fit: contain; cursor: pointer;" />`
}

marked.setOptions({
  renderer: render,
  gfm: true,
  pedantic: false,
})

const selectedTaskId = computed(() => indexStore.SelectedTaskID)

function setupImagePreview() {
  if (!mdContainer.value) return
  const images = mdContainer.value.querySelectorAll("img.preview-image")
  images.forEach((img) => {
    ;(img as HTMLImageElement).onclick = () => {
      previewSrc.value = (img as HTMLImageElement).src
      nextTick(() => previewImageRef.value?.click())
    }
  })
}

watch(
  selectedTaskId,
  async (newTaskId) => {
    const interfaceTask = interfaceStore.interface?.task
    if (!interfaceTask?.length) return

    for (const task of interfaceTask) {
      if (task.entry === newTaskId) {
        md.value = task.description
          ? DOMPurify.sanitize(marked.parse(task.description) as string)
          : (marked(t("panel.empty")) as string)
        nextTick(() => setupImagePreview())
        break
      }
    }
  },
  { immediate: true },
)
</script>
