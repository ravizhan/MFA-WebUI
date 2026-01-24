<template>
  <div class="flex flex-col h-full">
    <div class="col-name">任务设置</div>
    <n-card
      hoverable
      content-style="padding: 0; display: flex; flex-direction: column; flex: 1; min-height: 0;"
      class="min-h-0 flex flex-col transition-all duration-300"
      :style="{ flex: settingsFlex }"
    >
      <n-scrollbar trigger="none" class="flex-1">
        <n-list v-if="!isEmpty" hoverable>
          <OptionItem v-for="optName in rootOptions" :key="optName" :name="optName" />
        </n-list>
        <div v-else class="py-[12px] px-[20px]">空空如也</div>
      </n-scrollbar>
    </n-card>

    <div class="col-name">任务说明</div>
    <n-card
      hoverable
      content-style="padding: 0.5rem 1rem; display: flex; flex-direction: column; flex: 1; min-height: 0;"
      class="min-h-0 flex flex-col transition-all duration-300"
      :style="{ flex: descriptionFlex }"
    >
      <n-scrollbar trigger="none" class="flex-1">
        <div ref="mdContainer" class="markdown-body" v-html="md"></div>
      </n-scrollbar>
    </n-card>
  </div>
  <!-- 隐藏的 n-image 用于预览 -->
  <n-image ref="previewImageRef" :src="previewSrc" :show-toolbar="true" style="display: none" />
</template>
<script setup lang="ts">
import { marked } from "marked"
import type { Tokens } from "marked"
import { ref, watch, nextTick, computed } from "vue"
import { useInterfaceStore } from "../stores/interface.ts"
import { useIndexStore } from "../stores"
import { NImage } from "naive-ui"
import OptionItem from "./OptionItem.vue"

const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const md = ref("")
const isEmpty = ref(true)
const rootOptions = ref<string[]>([])

const settingsFlex = computed(() => {
  // 至少保留约 3 行的高度权重，每个选项增加权重
  const weight = Math.max(3, rootOptions.value.length)
  // 如果两个内容都很少，权重接近，平分
  // 如果此部分很大，权重变大，占据更多比例
  return `${weight} ${weight} 0px`
})

const descriptionFlex = computed(() => {
  // Markdown 内容以字符长度估算
  // 300 字符约为 3 行选项的高度权重 (300/100 = 3)
  const weight = Math.max(3, md.value.length / 100)
  return `${weight} ${weight} 0px`
})

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
