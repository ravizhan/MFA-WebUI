<template>
  <div class="col-name">任务设置</div>
  <n-card hoverable>114514</n-card>
  <div class="col-name">任务说明</div>
  <n-card hoverable content-style="padding-top: 0.5rem;">
    <n-scrollbar class="max-h-90" trigger="none">
      <div class="prose prose-sm dark:prose-invert" v-html="md"></div>
    </n-scrollbar>
  </n-card>
</template>
<script setup lang="ts">
import { marked } from 'marked'
import { ref, watch } from 'vue'
import { useInterfaceStore } from '../stores/interface.ts'
import { useIndexStore } from '../stores'

const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const md = ref<HTMLElement | null>(null)

const render = new marked.Renderer()
marked.setOptions({
  renderer: render,
  gfm: true,
  pedantic: false,
})

watch(
  () => indexStore.SelectedTaskID,
  (newTaskId) => {
    console.log(newTaskId)
    const interface_task = interfaceStore.interface?.task
    // console.log(interface_task)
    for (const i of interface_task!) {
      if (i.entry === newTaskId) {
        if (Array.isArray(i.doc)) {
          md.value = marked(i.doc.join('\n')) as unknown as HTMLElement
        }
        break
      }
    }
  },
)
</script>
