<template>
  <template v-if="option">
    <n-list-item>
      <div
        :style="{ paddingLeft: (level || 0) * 20 + 'px' }"
        class="flex items-center justify-between w-full gap-4"
      >
        <div class="min-w-0 flex-1">{{ resolvedLabel }}</div>
        <div class="flex flex-1 justify-end">
          <template v-if="option.type === 'switch'">
            <n-switch
              :checked-value="checkedValue"
              :unchecked-value="uncheckedValue"
              :round="false"
              v-model:value="options[name]"
            />
          </template>

          <template v-else-if="option.type === 'select'">
            <n-select
              class="w-full max-w-xs"
              :options="selectOptions"
              v-model:value="options[name]"
            />
          </template>

          <template v-else-if="option.type === 'scan_select'">
            <div class="flex w-full max-w-xs items-center gap-2">
              <n-select class="flex-1" :options="selectOptions" v-model:value="options[name]" />
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

          <template v-else-if="option.type === 'input'">
            <div class="flex w-full max-w-sm flex-col gap-2">
              <div v-for="input in option.inputs" :key="input.name" class="flex flex-col gap-1">
                <span class="text-sm text-gray-500">{{
                  resolveInputLabel(input.label, input.name)
                }}</span>
                <n-input
                  v-model:value="options[`${name}_${input.name}`]"
                  :allow-input="(v: string) => handleAllowInput(v, input.verify, input.pattern_msg)"
                />
              </div>
            </div>
          </template>

          <template v-else-if="option.type === 'checkbox'">
            <n-checkbox-group v-model:value="checkboxValue">
              <n-space item-style="display: flex;" align="center">
                <div v-for="checkbox in option.cases" :key="checkbox.name">
                  <n-checkbox
                    :value="checkbox.name"
                    :label="resolveCaseLabel(checkbox.label, checkbox.name)"
                  />
                </div>
              </n-space>
            </n-checkbox-group>
          </template>
        </div>
      </div>
    </n-list-item>

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
import { storeToRefs } from "pinia"
import { useMessage } from "naive-ui"
import { useI18n } from "vue-i18n"
import { useInterfaceStore, useTaskConfigStore } from "@/stores"
import type { TaskOptionValue } from "@/types/scheduler/model"
import { resolveInterfaceText } from "@/utils/interface/content"

const props = defineProps<{
  name: string
  level?: number
  options?: Record<string, TaskOptionValue>
}>()

const message = useMessage()
const { locale } = useI18n()
const interfaceStore = useInterfaceStore()
const configStore = useTaskConfigStore()
const options = props.options ? computed(() => props.options!) : storeToRefs(configStore).options

const option = computed(() => interfaceStore.interface?.option?.[props.name])
const resolvedLabel = computed(() =>
  resolveInterfaceText(interfaceStore.interface, locale.value, option.value?.label, props.name),
)
const scanSelectRefreshing = ref(false)

const checkedValue = computed(() => {
  const currentOption = option.value
  if (!currentOption || currentOption.type !== "switch") {
    return ""
  }
  return ["Yes", "yes", "Y", "y"].includes(currentOption.cases[1].name)
    ? currentOption.cases[1].name
    : currentOption.cases[0].name
})

const uncheckedValue = computed(() => {
  const currentOption = option.value
  if (!currentOption || currentOption.type !== "switch") {
    return ""
  }
  return ["Yes", "yes", "Y", "y"].includes(currentOption.cases[1].name)
    ? currentOption.cases[0].name
    : currentOption.cases[1].name
})

function resolveCaseLabel(label: string | undefined, fallback: string) {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

function resolveInputLabel(label: string | undefined, fallback: string) {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

async function handleRescanScanSelect() {
  const currentOption = option.value
  if (!currentOption || currentOption.type !== "scan_select") {
    return
  }

  const previousValue = options.value[props.name]
  scanSelectRefreshing.value = true
  try {
    options.value[props.name] = null as never
    await interfaceStore.rescanScanSelectOption(props.name)
  } catch (error) {
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
    const currentOption = option.value
    if (!currentOption || currentOption.type !== "checkbox") {
      return []
    }

    return normalizeCheckboxValue(
      options.value[props.name],
      currentOption.cases.map((item) => item.name),
    )
  },
  set(value) {
    const currentOption = option.value
    if (!currentOption || currentOption.type !== "checkbox") {
      return
    }

    options.value[props.name] = normalizeCheckboxValue(
      value,
      currentOption.cases.map((item) => item.name),
    )
  },
})

const selectOptions = computed(() => {
  const currentOption = option.value
  if (currentOption?.type === "select" || currentOption?.type === "scan_select") {
    return currentOption.cases.map((caseItem) => ({
      label: resolveCaseLabel(caseItem.label, caseItem.name),
      value: caseItem.name,
    }))
  }
  return []
})

const isSelectValueInvalid = computed(() => {
  const currentOption = option.value
  if (currentOption?.type !== "select" && currentOption?.type !== "scan_select") {
    return false
  }

  const currentValue = options.value[props.name]
  if (currentValue == null || typeof currentValue !== "string") {
    return false
  }

  return !selectOptions.value.some((item) => item.value === currentValue)
})

watch(
  () => isSelectValueInvalid.value,
  (invalid) => {
    if (invalid) {
      options.value[props.name] = null as never
    }
  },
  { immediate: true },
)

const nestedOptions = computed(() => {
  const currentOption = option.value
  if (!currentOption) return []
  const currentValue = options.value[props.name]

  if (currentOption.type === "switch") {
    const activeCase = currentOption.cases.find((caseItem) => caseItem.name === currentValue)
    return activeCase?.option || []
  }

  if (currentOption.type === "select" || currentOption.type === "scan_select") {
    const activeCase = currentOption.cases.find((caseItem) => caseItem.name === currentValue)
    return activeCase?.option || []
  }

  if (currentOption.type === "checkbox") {
    const activeNames = new Set(
      normalizeCheckboxValue(
        options.value[props.name],
        currentOption.cases.map((item) => item.name),
      ),
    )
    const childNames: string[] = []
    const seen = new Set<string>()

    for (const caseItem of currentOption.cases) {
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

function handleAllowInput(value: string, verify?: string, patternMessage?: string) {
  if (!verify || value === "") return true
  try {
    const isValid = new RegExp(verify).test(value)
    if (!isValid && patternMessage) {
      message.error(
        resolveInterfaceText(
          interfaceStore.interface,
          locale.value,
          patternMessage,
          patternMessage,
        ),
      )
    }
    return isValid
  } catch {
    return true
  }
}
</script>
