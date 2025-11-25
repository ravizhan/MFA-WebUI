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
import type { Option, SelectOption, InputOption, InputCase } from '../types/interfaceV2.ts'
import { storeToRefs } from 'pinia'

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
  checkbox: Record<string, string>
  input: Record<string, InputCase[]>
}
const option_dict = ref<ProcessedOptions>({
  select: {},
  checkbox: {},
  input: {},
})
const options = storeToRefs(interfaceStore).options

function process_options(origin: Record<string, Option>): ProcessedOptions {
  const result: ProcessedOptions = {
    select: {},
    checkbox: {},
    input: {},
  }
  for (const key in origin) {
    const option = origin[key]!
    if (option.type === 'select') {
      const selectOption = option as SelectOption
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
      const inputOption = option as InputOption
      result.input[key] = inputOption.inputs
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
    if (!interface_task || interface_task.length === 0) {
      return
    }
    for (const i of interface_task!) {
      if (i.entry === newTaskId) {
        if (i.description) {
          md.value = marked(i.description) as unknown as HTMLElement
        } else {
          md.value = marked('空空如也') as unknown as HTMLElement
        }
        option_dict.value = process_options(interfaceStore.getOptionList(i.entry))
        isEmpty.value = !(
          Object.keys(option_dict.value.select).length > 0 ||
          Object.keys(option_dict.value.checkbox).length > 0 ||
          Object.keys(option_dict.value.input).length > 0
        )
        break
      }
    }
  },
  { immediate: true },
)
</script>
