<template>
  <template v-if="option">
    <n-list-item>
      <div
        :style="{ paddingLeft: (level || 0) * 20 + 'px' }"
        class="flex items-center justify-between w-full"
      >
        <div class="mr-4">{{ label || name }}</div>
        <div class="flex-1 flex justify-end">
          <!-- Switch -->
          <template v-if="option.type === 'switch'">
            <n-switch
              :checked-value="
                ['Yes', 'yes', 'Y', 'y'].includes(option.cases[1].name)
                  ? option.cases[1].name
                  : option.cases[0].name
              "
              :unchecked-value="
                ['Yes', 'yes', 'Y', 'y'].includes(option.cases[1].name)
                  ? option.cases[0].name
                  : option.cases[1].name
              "
              :round="false"
              v-model:value="options[name]"
            />
          </template>
          <!-- Select -->
          <template v-else-if="option.type === 'select'">
            <n-select class="w-40" :options="selectOptions" v-model:value="options[name]" />
          </template>
          <!-- Scan Select -->
          <template v-else-if="option.type === 'scan_select'">
            <div class="flex items-center gap-2">
              <n-select class="w-40" :options="selectOptions" v-model:value="options[name]" />
              <n-button
                circle
                quaternary
                size="small"
                :loading="scanSelectRefreshing"
                :disabled="scanSelectRefreshing"
                @click="handleRescanScanSelect"
              >
                <template #icon>
                  <n-icon>
                    <div class="i-mdi-refresh" />
                  </n-icon>
                </template>
              </n-button>
            </div>
          </template>
          <!-- Input -->
          <template v-else-if="option.type === 'input'">
            <div class="flex flex-col gap-2 w-full max-w-xs">
              <div v-for="input in option.inputs" :key="input.name" class="flex flex-col gap-1">
                <span class="text-sm text-gray-500">{{ input.label || input.name }}</span>
                <n-input
                  v-model:value="options[`${name}_${input.name}`]"
                  :allow-input="(v: string) => handleAllowInput(v, input.verify, input.pattern_msg)"
                />
              </div>
            </div>
          </template>
          <!-- checkbox -->
          <template v-else-if="option.type === 'checkbox'">
            <n-checkbox-group v-model:value="checkboxValue">
              <n-space item-style="display: flex;" align="center">
                <div v-for="checkbox in option.cases" :key="checkbox.name">
                  <n-checkbox :value="checkbox.name" :label="checkbox.label || checkbox.name" />
                </div>
              </n-space>
            </n-checkbox-group>
          </template>
        </div>
      </div>
    </n-list-item>

    <!-- Recursive children -->
    <template v-if="nestedOptions.length > 0">
      <OptionItem
        v-for="childName in nestedOptions"
        :key="childName"
        :name="childName"
        :level="(level || 0) + 1"
        :options="options"
      />
    </template>
  </template>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useInterfaceStore } from "../stores/interface"
import { useTaskConfigStore } from "../stores/taskConfig"
import { storeToRefs } from "pinia"
import { useMessage } from "naive-ui"
import type { TaskOptionValue } from "../types/scheduler"

const props = defineProps<{
  name: string
  level?: number
  options?: Record<string, TaskOptionValue>
}>()

const message = useMessage()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const options = props.options ? computed(() => props.options!) : storeToRefs(configStore).options

const option = computed(() => interfaceStore.interface?.option?.[props.name])
const label = computed(() => option.value?.label)
const scanSelectRefreshing = ref(false)

async function handleRescanScanSelect() {
  const opt = option.value
  if (!opt || opt.type !== "scan_select") {
    return
  }

  // 在重扫前保存旧值，避免请求失败导致用户选择丢失
  const previousValue = options.value[props.name]

  scanSelectRefreshing.value = true
  try {
    options.value[props.name] = null as any
    await interfaceStore.rescanScanSelectOption(props.name)
  } catch (error) {
    // 重扫失败时恢复旧值
    options.value[props.name] = previousValue
    if (error instanceof Error && error.message) {
      message.error(error.message)
    }
  } finally {
    scanSelectRefreshing.value = false
  }
}

function normalizeCheckboxValue(value: TaskOptionValue | undefined, caseOrder: string[]): string[] {
  let selectedValues: string[] = []

  if (Array.isArray(value)) {
    selectedValues = value.filter((item): item is string => typeof item === "string")
  } else if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) {
        selectedValues = parsed.filter((item): item is string => typeof item === "string")
      }
    } catch {
      selectedValues = []
    }
  }

  const selectedSet = new Set(selectedValues)
  return caseOrder.filter((name) => selectedSet.has(name))
}

const checkboxValue = computed<string[]>({
  get() {
    const opt = option.value
    if (!opt || opt.type !== "checkbox") {
      return []
    }

    return normalizeCheckboxValue(
      options.value[props.name],
      opt.cases.map((item) => item.name),
    )
  },
  set(value) {
    const opt = option.value
    if (!opt || opt.type !== "checkbox") {
      return
    }

    options.value[props.name] = normalizeCheckboxValue(
      value,
      opt.cases.map((item) => item.name),
    )
  },
})

const selectOptions = computed(() => {
  const opt = option.value
  if (opt?.type === "select" || opt?.type === "scan_select") {
    return opt.cases.map((c) => ({
      label: c.label || c.name,
      value: c.name,
    }))
  }
  return []
})

watch(
  () => [selectOptions.value, options.value[props.name]] as const,
  ([newOptions, currentVal]) => {
    const opt = option.value
    if (opt?.type === "select" || opt?.type === "scan_select") {
      if (currentVal != null && typeof currentVal === "string") {
        const exists = newOptions.some((o) => o.value === currentVal)
        if (!exists) {
          options.value[props.name] = null as any
        }
      }
    }
  },
  { immediate: true, deep: true },
)

const nestedOptions = computed(() => {
  const opt = option.value
  if (!opt) return []
  const currentVal = options.value[props.name]

  if (opt.type === "switch") {
    const activeCase = opt.cases.find((c) => c.name === currentVal)
    return activeCase?.option || []
  }

  if (opt.type === "select" || opt.type === "scan_select") {
    const activeCase = opt.cases.find((c) => c.name === currentVal)
    return activeCase?.option || []
  }

  if (opt.type === "checkbox") {
    const activeNames = new Set(
      normalizeCheckboxValue(
        options.value[props.name],
        opt.cases.map((item) => item.name),
      ),
    )
    const childNames: string[] = []
    const seen = new Set<string>()

    for (const caseItem of opt.cases) {
      if (!activeNames.has(caseItem.name)) {
        continue
      }

      for (const childName of caseItem.option || []) {
        if (seen.has(childName)) {
          continue
        }
        seen.add(childName)
        childNames.push(childName)
      }
    }

    return childNames
  }

  return []
})

const handleAllowInput = (value: string, verify?: string, pattern_msg?: string) => {
  if (!verify || value === "") return true
  try {
    const isValid = new RegExp(verify).test(value)
    if (!isValid && pattern_msg) {
      message.error(pattern_msg)
    }
    return isValid
  } catch (e) {
    return true
  }
}
</script>
