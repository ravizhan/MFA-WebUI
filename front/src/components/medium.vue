<template>
  <div class="col-name">任务设置</div>
  <n-card hoverable>
    <n-list v-if="!isEmpty" hoverable>
      <n-list-item v-for="(value, k) in option_dict['select']" :key="k">
        <div>{{ k }}</div>
        <n-select :options="value" />
      </n-list-item>
      <n-list-item v-for="(value, k) in option_dict['checkbox']" :key="k">
        <div>{{ k }}</div>
        <template #suffix>
          <n-switch checked-value="周末加班" unchecked-value="周末支持一下" :round="false" />
        </template>
      </n-list-item>
    </n-list>
    <div v-else class="py-[12px] px-[20px]">空空如也</div>
  </n-card>
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
import type { Option } from '../types/interfaceV1.ts'

const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const md = ref<HTMLElement | null>(null)
const isEmpty = ref(true)
const render = new marked.Renderer()
marked.setOptions({
  renderer: render,
  gfm: true,
  pedantic: false,
})
type ProcessedOptions = {
  select: Record<string, object>
  checkbox: Record<string, object>
}
const option_dict = ref<ProcessedOptions>({
  select: {},
  checkbox: {},
})

function process_options(origin: Record<string, Option>): ProcessedOptions {
  const result: ProcessedOptions = {
    select: {},
    checkbox: {},
  }
  for (const key in origin) {
    const optionCases = origin[key]!.cases
    if (optionCases[0]!.name === 'no' || optionCases[0]!.name === 'yes') {
      result.checkbox[key] = optionCases
    } else {
      result.select[key] = optionCases.map((item, index) => ({
        label: item.name,
        value: JSON.stringify(optionCases[index]),
      }))
    }
  }
  return result
}

watch(
  () => indexStore.SelectedTaskID,
  (newTaskId) => {
    // console.log(newTaskId)
    const interface_task = interfaceStore.interface?.task
    // console.log(interface_task)
    for (const i of interface_task!) {
      if (i.entry === newTaskId) {
        if (Array.isArray(i.doc)) {
          md.value = marked(i.doc.join('\n\n')) as unknown as HTMLElement
        } else if (typeof i.doc === 'string') {
          md.value = marked(i.doc) as unknown as HTMLElement
        } else {
          md.value = "<div>空空如也</div>" as unknown as HTMLElement
        }
        option_dict.value = process_options(interfaceStore.getOptionList(i.entry))
        isEmpty.value = !(
          Object.keys(option_dict.value.select).length > 0 ||
          Object.keys(option_dict.value.checkbox).length > 0
        )
        break
      }
    }
  },
)
</script>
