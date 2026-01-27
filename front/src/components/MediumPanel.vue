<template>
  <div class="col-name">任务设置</div>
  <n-card
    hoverable
    content-style="padding: 0;"
    class="transition-all duration-300 overflow-hidden"
  >
    <n-scrollbar trigger="none" class="max-h-65 !rounded-[12px]">
      <n-list v-if="!isEmpty" hoverable>
        <OptionItem v-for="optName in rootOptions" :key="optName" :name="optName" />
      </n-list>
      <div v-else class="py-[12px] px-[20px] min-h-50">空空如也</div>
    </n-scrollbar>
  </n-card>

  <div class="col-name">任务说明</div>
  <n-card
    hoverable
    content-style="padding: 0.5rem 1rem;"
    class="transition-all duration-300"
  >
    <n-scrollbar trigger="none">
      <div ref="mdContainer" class="markdown-body min-h-50 max-h-65" v-html="md"></div>
    </n-scrollbar>
  </n-card>
  <!-- 隐藏的 n-image 用于预览 -->
  <n-image ref="previewImageRef" :src="previewSrc" :show-toolbar="true" style="display: none" />
</template>
<script setup lang="ts">
import { marked } from "marked"
import type { Tokens } from "marked"
import { ref, watch, nextTick } from "vue"
import { useInterfaceStore } from "../stores/interface.ts"
import { useIndexStore } from "../stores"
import { NImage } from "naive-ui"
import OptionItem from "./OptionItem.vue"

const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const md = ref("")
const isEmpty = ref(true)
const rootOptions = ref<string[]>([])

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

function setupImagePreview() {
  if (!mdContainer.value) return
  const images = mdContainer.value.querySelectorAll("img.preview-image")
  images.forEach((img) => {
    ;(img as HTMLImageElement).onclick = () => {
      previewSrc.value = (img as HTMLImageElement).src
      nextTick(() => {
        previewImageRef.value?.click()
      })
    }
  })
}

marked.setOptions({
  renderer: render,
  gfm: true,
  pedantic: false,
})


watch(
  () => indexStore.SelectedTaskID,
  async (newTaskId) => {
    // console.log(newTaskId)
    const interface_task = interfaceStore.interface?.task
    // console.log(interface_task)
    if (!interface_task || interface_task.length === 0) {
      return
    }
    for (const i of interface_task!) {
      if (i.entry === newTaskId) {
        if (i.description) {
          md.value = await marked(i.description)
        } else {
          md.value = await marked("空空如也")
        }
        
        rootOptions.value = i.option || []
        isEmpty.value = rootOptions.value.length === 0
        
        nextTick(() => {
          setupImagePreview()
        })
        break
      }
    }
  },
  { immediate: true },
)
</script>
