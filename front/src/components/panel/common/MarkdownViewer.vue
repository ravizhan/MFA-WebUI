<template>
  <n-scrollbar trigger="none">
    <div ref="mdContainer" class="markdown-body" :class="bodyClass" v-html="htmlContent"></div>
  </n-scrollbar>
  <n-image ref="previewImageRef" :src="previewSrc" :show-toolbar="true" style="display: none" />
</template>

<script setup lang="ts">
import DOMPurify from "dompurify"
import { marked } from "marked"
import type { Tokens } from "marked"
import { NImage } from "naive-ui"
import { computed, nextTick, ref, watch } from "vue"
import { buildInterfaceResourceUrl, isExternalUrl } from "@/utils/interface/content"

const props = withDefaults(
  defineProps<{
    source: string
    emptyText?: string
    bodyClass?: string
  }>(),
  {
    emptyText: "",
    bodyClass: "min-h-50 max-h-65",
  },
)

const mdContainer = ref<HTMLElement | null>(null)
const previewImageRef = ref<InstanceType<typeof NImage> | null>(null)
const previewSrc = ref("")
const render = new marked.Renderer()

render.image = function ({ href, title, text }: Tokens.Image) {
  const rawHref = href || ""
  const safeHref =
    rawHref && !isExternalUrl(rawHref) && !rawHref.startsWith("/")
      ? buildInterfaceResourceUrl(rawHref)
      : rawHref
  const titleAttr = title ? ` title="${title}"` : ""
  const altAttr = text ? ` alt="${text}"` : ""
  return `<img src="${safeHref}"${titleAttr}${altAttr} class="preview-image" style="max-width: 100%; object-fit: contain; cursor: pointer;" />`
}

marked.setOptions({
  renderer: render,
  gfm: true,
  pedantic: false,
})

const htmlContent = computed(() => {
  const source = props.source?.trim() ? props.source : props.emptyText
  return DOMPurify.sanitize(marked.parse(source || "") as string)
})

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
  htmlContent,
  () => {
    nextTick(() => setupImagePreview())
  },
  { immediate: true },
)
</script>
