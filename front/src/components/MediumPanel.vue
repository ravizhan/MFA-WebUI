<template>
  <div class="col-name">任务设置</div>
  <n-card hoverable>
    <n-list v-if="!isEmpty" hoverable>
      <n-list-item v-for="(value, k) in option_dict['select']" :key="k">
        <div>{{ k }}</div>
        <n-select :options="value" v-model:value="options[k]" />
      </n-list-item>
      <n-list-item v-for="(value, k) in option_dict['input']" :key="k">
        <div>{{ k }}</div>
        <div class="flex flex-col gap-2 w-full">
          <div v-for="input in value" :key="input.name" class="flex flex-col gap-1">
            <span class="text-sm text-gray-500">{{ input.label || input.name }}</span>
            <n-input v-model:value="options[`${k}_${input.name}`]" />
          </div>
        </div>
      </n-list-item>
      <n-list-item v-for="(_, k) in option_dict['checkbox']" :key="k">
        <div>{{ k }}</div>
        <template #suffix>
          <n-switch
            checked-value="yes"
            unchecked-value="no"
            :round="false"
            v-model:value="options[k]"
          />
        </template>
      </n-list-item>
      <n-list-item v-for="(switchValues, k) in option_dict['switch']" :key="k">
        <div>{{ k }}</div>
        <template #suffix>
          <n-switch
            :checked-value="switchValues[1]"
            :unchecked-value="switchValues[0]"
            :round="false"
            v-model:value="options[k]"
          />
        </template>
      </n-list-item>
    </n-list>
    <div v-else class="py-[12px] px-[20px]">空空如也</div>
  </n-card>
  <div class="col-name">任务说明</div>
  <n-card hoverable content-style="padding-top: 0.5rem;">
    <n-scrollbar class="max-h-90" trigger="none">
      <div ref="mdContainer" class="markdown-body" v-html="md"></div>
    </n-scrollbar>
  </n-card>
  <!-- 隐藏的 n-image 用于预览 -->
  <n-image ref="previewImageRef" :src="previewSrc" :show-toolbar="true" style="display: none" />
</template>
<script setup lang="ts">
import { marked } from 'marked'
import type { Tokens } from 'marked'
import { ref, watch, nextTick } from 'vue'
import { useInterfaceStore } from '../stores/interface.ts'
import { useIndexStore } from '../stores'
import { NImage } from 'naive-ui'
import type { SelectOption as NaiveSelectOption } from 'naive-ui'
import type {
  Option,
  SelectOption as TaskSelectOption,
  InputOption as TaskInputOption,
  SwitchOption as TaskSwitchOption,
  InputCase,
} from '../types/interfaceV2.ts'
import { storeToRefs } from 'pinia'

const interfaceStore = useInterfaceStore()
const indexStore = useIndexStore()
const md = ref('')
const isEmpty = ref(true)
const mdContainer = ref<HTMLElement | null>(null)
const previewImageRef = ref<InstanceType<typeof NImage> | null>(null)
const previewSrc = ref('')
const render = new marked.Renderer()

render.image = function ({ href, title, text }: Tokens.Image) {
  const safeHref = href || ''
  const titleAttr = title ? ` title="${title}"` : ''
  const altAttr = text ? ` alt="${text}"` : ''
  return `<img src="${safeHref}"${titleAttr}${altAttr} class="preview-image" style="max-width: 100%; object-fit: contain; cursor: pointer;" />`
}

function setupImagePreview() {
  if (!mdContainer.value) return
  const images = mdContainer.value.querySelectorAll('img.preview-image')
  images.forEach((img) => {
    (img as HTMLImageElement).onclick = () => {
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
  pedantic: false
})

type ProcessedOptions = {
  select: Record<string, NaiveSelectOption[]>
  checkbox: Record<string, string>
  input: Record<string, InputCase[]>
  switch: Record<string, [string, string]>
}
const option_dict = ref<ProcessedOptions>({
  select: {},
  checkbox: {},
  input: {},
  switch: {},
})
const options = storeToRefs(interfaceStore).options

function process_options(origin: Record<string, Option>): ProcessedOptions {
  const result: ProcessedOptions = {
    select: {},
    checkbox: {},
    input: {},
    switch: {},
  }
  for (const key in origin) {
    const option = origin[key]!
    if (option.type === 'select') {
      const selectOption = option as TaskSelectOption
      const cases = selectOption.cases
      if (cases.length > 0 && (cases[0]!.name === 'no' || cases[0]!.name === 'yes')) {
        result.checkbox[key] = selectOption.default_case || 'no'
      } else {
        result.select[key] = cases.map((item) => ({
          label: item.label || item.name,
          value: item.name,
        }))
      }
    } else if (option.type === 'input') {
      const inputOption = option as TaskInputOption
      result.input[key] = inputOption.inputs
    } else if (option.type === 'switch') {
      const switchOption = option as TaskSwitchOption
      result.switch[key] = [switchOption.cases[0]!.name, switchOption.cases[1]!.name]
    }
  }
  return result
}

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
          md.value = await marked('空空如也')
        }
        option_dict.value = process_options(interfaceStore.getOptionList(i.entry))
        isEmpty.value = !(
          Object.keys(option_dict.value.select).length > 0 ||
          Object.keys(option_dict.value.checkbox).length > 0 ||
          Object.keys(option_dict.value.input).length > 0 ||
          Object.keys(option_dict.value.switch).length > 0
        )
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
