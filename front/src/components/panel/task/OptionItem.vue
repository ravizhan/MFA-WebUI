<template>
  <template v-if="option">
    <div
      class="flex items-center justify-between w-full gap-4 py-2 px-3 border-b border-solid last:border-b-0"
      :style="{
        paddingLeft: (level || 0) * 20 + 12 + 'px',
        borderBottomColor: 'var(--divider-color)',
      }"
    >
      <div class="min-w-0 flex-1 text-sm">{{ resolvedLabel }}</div>
      <div class="flex flex-1 justify-end">
        <template v-if="option.type === 'switch'">
          <NSwitch
            size="small"
            :value="taskOptions[name] === checkedValue"
            @update:value="handleSwitchValueChange"
          />
        </template>

        <template v-else-if="option.type === 'select'">
          <NSelect
            v-model:value="selectValue"
            size="small"
            class="w-full max-w-xs"
            :options="selectOptions"
          />
        </template>

        <template v-else-if="option.type === 'scan_select'">
          <OptionScanSelectControl
            v-model:value="selectValue"
            :options="selectOptions"
            :refreshing="scanSelectRefreshing"
            @rescan="handleRescanScanSelect"
          />
        </template>

        <template v-else-if="option.type === 'input'">
          <div class="flex w-full max-w-sm flex-col gap-2">
            <div v-for="input in option.inputs" :key="input.name" class="flex flex-col gap-1">
              <span class="text-xs opacity-60">{{
                resolveInputLabel(input.label, input.name)
              }}</span>
              <NInputNumber
                v-if="getInputControlType(input) === 'number'"
                size="small"
                :value="getInputNumberValue(input.name)"
                :status="isInputError(input.name, input.verify) ? 'error' : undefined"
                @update:value="handleInputNumberChange(input.name, $event, input)"
              />
              <NSwitch
                v-else-if="getInputControlType(input) === 'bool'"
                size="small"
                :value="getBooleanInputValue(input.name)"
                @update:value="handleBooleanInputChange(input.name, $event, input)"
              />
              <NInput
                v-else-if="getInputControlType(input) === 'textarea'"
                type="textarea"
                size="small"
                :value="getInputValue(input.name)"
                :status="isInputError(input.name, input.verify) ? 'error' : undefined"
                @update:value="handleInputChange(input.name, $event, input)"
              />
              <NInput
                v-else
                size="small"
                :value="getInputValue(input.name)"
                :status="isInputError(input.name, input.verify) ? 'error' : undefined"
                @update:value="handleInputChange(input.name, $event, input)"
              />
            </div>
          </div>
        </template>

        <template v-else-if="option.type === 'checkbox'">
          <div class="flex flex-wrap gap-3">
            <NCheckbox
              v-for="checkbox in option.cases"
              :key="checkbox.name"
              :checked="checkboxValue.includes(checkbox.name)"
              @update:checked="handleCheckboxChange(checkbox.name, $event)"
            >
              {{ resolveCaseLabel(checkbox.label, checkbox.name) }}
            </NCheckbox>
          </div>
        </template>
      </div>
    </div>

    <template v-if="nestedOptions.length > 0">
      <OptionItem
        v-for="childName in nestedOptions"
        :key="childName"
        :name="childName"
        :level="(level || 0) + 1"
        :task-options="taskOptions"
      />
    </template>
  </template>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useI18n } from "vue-i18n"
import { NCheckbox, NInput, NInputNumber, NSelect, NSwitch } from "naive-ui"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore } from "@/stores"
import type { InputCase } from "@/types/interfaceModel"
import type { NullableTaskOptionValue } from "@/types/schedulerModel"
import { makeInterfaceInputSchema } from "@/validation/interfaceInput"
import { resolveInterfaceText } from "@/utils/interface/content"
import { tryCatch } from "@/utils/tryCatch"
import OptionScanSelectControl from "@/components/panel/task/OptionScanSelectControl.vue"

const {
  name,
  level,
  taskOptions: rawTaskOptions,
} = defineProps<{
  name: string
  level?: number
  taskOptions: Record<string, NullableTaskOptionValue>
}>()
// sync setup
const { locale } = useI18n()
const interfaceStore = useInterfaceStore()
const taskOptions = computed(() => rawTaskOptions)

const option = computed(() => interfaceStore.interface?.option?.[name])
const resolvedLabel = computed(() =>
  resolveInterfaceText(interfaceStore.interface, locale.value, option.value?.label, name),
)
const scanSelectRefreshing = ref(false)
/** Tracks which input fields currently fail verify, for one-shot pattern_msg on invalid transition. */
const inputInvalidState = ref<Record<string, boolean>>({})

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

function isInputAllowed(value: string, verify?: string): boolean {
  if (!verify || value === "") return true
  return makeInterfaceInputSchema(verify).safeParse(value).success
}

function isInputError(inputName: string, verify?: string): boolean {
  // Current model value fails verify (e.g. preloaded invalid); blocked keystrokes never enter model
  return !isInputAllowed(getInputValue(inputName), verify)
}

function getInputValue(inputName: string): string {
  const currentValue = taskOptions.value[name]
  if (currentValue && typeof currentValue === "object" && !Array.isArray(currentValue)) {
    const inputValue = currentValue[inputName]
    return typeof inputValue === "string" ? inputValue : ""
  }
  return ""
}

function setInputValue(inputName: string, value: string): void {
  const currentValue = taskOptions.value[name]
  const nextValue: Record<string, string> =
    currentValue && typeof currentValue === "object" && !Array.isArray(currentValue)
      ? { ...currentValue }
      : {}

  nextValue[inputName] = value
  taskOptions.value[name] = nextValue
}

function handleInputChange(inputName: string, value: string, input: InputCase): void {
  const allowed = isInputAllowed(value, input.verify)
  const wasInvalid = inputInvalidState.value[inputName] === true

  if (allowed) {
    setInputValue(inputName, value)
    inputInvalidState.value = { ...inputInvalidState.value, [inputName]: false }
    return
  }

  // Invalid: do not update model; the controlled Naive UI input retains the previous value.
  inputInvalidState.value = { ...inputInvalidState.value, [inputName]: true }
  if (!wasInvalid && input.pattern_msg) {
    const msg = resolveInterfaceText(
      interfaceStore.interface,
      locale.value,
      input.pattern_msg,
      input.pattern_msg,
    )
    showGlobalMessage("error", msg)
  }
}

async function handleRescanScanSelect() {
  const currentOption = option.value
  if (!currentOption || currentOption.type !== "scan_select") {
    return
  }

  const previousValue = taskOptions.value[name]
  scanSelectRefreshing.value = true
  taskOptions.value[name] = null
  const [, err] = await tryCatch(() => interfaceStore.rescanScanSelectOption(name))
  if (err) {
    taskOptions.value[name] = previousValue
    if (err.message) {
      showGlobalMessage("error", err.message)
    }
  }
  scanSelectRefreshing.value = false
}

function parseStringArray(value: string): string[] {
  const [parsed, err] = tryCatch(() => JSON.parse(value))
  if (err || !Array.isArray(parsed)) return []
  return parsed.filter((item): item is string => typeof item === "string")
}

function normalizeCheckboxValue(
  value: NullableTaskOptionValue | undefined,
  caseOrder: string[],
): string[] {
  let selectedValues: string[] = []

  if (Array.isArray(value)) {
    selectedValues = value.filter((item): item is string => typeof item === "string")
  } else if (typeof value === "string") {
    selectedValues = parseStringArray(value)
  }

  const selectedSet = new Set(selectedValues)
  return caseOrder.filter((caseName) => selectedSet.has(caseName))
}

const checkboxValue = computed<string[]>({
  get() {
    const currentOption = option.value
    if (!currentOption || currentOption.type !== "checkbox") {
      return []
    }

    return normalizeCheckboxValue(
      taskOptions.value[name],
      currentOption.cases.map((item) => item.name),
    )
  },
  set(value) {
    const currentOption = option.value
    if (!currentOption || currentOption.type !== "checkbox") {
      return
    }

    taskOptions.value[name] = normalizeCheckboxValue(
      value,
      currentOption.cases.map((item) => item.name),
    )
  },
})

function handleCheckboxChange(checkboxName: string, checked: boolean) {
  const current = new Set(checkboxValue.value)
  if (checked) {
    current.add(checkboxName)
    checkboxValue.value = Array.from(current)
    return
  }
  current.delete(checkboxName)
  checkboxValue.value = Array.from(current)
}

function handleSwitchValueChange(value: string | number | boolean) {
  const checked = value === true || value === 1 || value === "true" || value === "1"
  taskOptions.value[name] = checked ? checkedValue.value : uncheckedValue.value
}

type InputControlType = "string" | "number" | "bool" | "textarea"

function getInputControlType(input: InputCase): InputControlType {
  const pipelineType: string | undefined = input.pipeline_type
  if (pipelineType === "int" || pipelineType === "number") {
    return "number"
  }
  if (pipelineType === "bool") {
    return "bool"
  }
  if (pipelineType === "textarea") {
    return "textarea"
  }
  return "string"
}

function getInputNumberValue(inputName: string): number | null {
  const value = getInputValue(inputName)
  if (!value.trim()) {
    return null
  }
  const numberValue = Number(value)
  return Number.isFinite(numberValue) ? numberValue : null
}

function handleInputNumberChange(inputName: string, value: number | null, input: InputCase) {
  handleInputChange(inputName, value == null ? "" : String(value), input)
}

function getBooleanInputValue(inputName: string): boolean {
  return ["true", "True", "TRUE", "yes", "Yes", "Y", "y", "1", "on", "On", "ON"].includes(
    getInputValue(inputName),
  )
}

function handleBooleanInputChange(
  inputName: string,
  value: string | number | boolean,
  input: InputCase,
) {
  const checked = value === true || value === 1 || value === "true" || value === "1"
  handleInputChange(inputName, checked ? "true" : "false", input)
}

const selectValue = computed<string | null>({
  get() {
    const value = taskOptions.value[name]
    return typeof value === "string" ? value : null
  },
  set(value) {
    taskOptions.value[name] = value
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

  const currentValue = taskOptions.value[name]
  if (currentValue == null || typeof currentValue !== "string") {
    return false
  }

  return !selectOptions.value.some((item) => item.value === currentValue)
})

watch(
  () => isSelectValueInvalid.value,
  (invalid) => {
    if (invalid) {
      taskOptions.value[name] = null
    }
  },
  { immediate: true },
)

function getSwitchNestedOptions(currentOption: NonNullable<typeof option.value>): string[] {
  const currentValue = taskOptions.value[name]
  const activeCase = currentOption.cases.find((caseItem) => caseItem.name === currentValue)
  return activeCase?.option || []
}

function getSelectNestedOptions(currentOption: NonNullable<typeof option.value>): string[] {
  const currentValue = taskOptions.value[name]
  const activeCase = currentOption.cases.find((caseItem) => caseItem.name === currentValue)
  return activeCase?.option || []
}

function getCheckboxNestedOptions(currentOption: NonNullable<typeof option.value>): string[] {
  const activeNames = new Set(
    normalizeCheckboxValue(
      taskOptions.value[name],
      currentOption.cases.map((item) => item.name),
    ),
  )
  const childNames: string[] = []
  const seen = new Set<string>()

  for (const caseItem of currentOption.cases) {
    if (!activeNames.has(caseItem.name)) continue

    for (const childName of caseItem.option || []) {
      if (seen.has(childName)) continue
      seen.add(childName)
      childNames.push(childName)
    }
  }

  return childNames
}

const nestedOptions = computed(() => {
  const currentOption = option.value
  if (!currentOption) return []

  if (currentOption.type === "switch") {
    return getSwitchNestedOptions(currentOption)
  }

  if (currentOption.type === "select" || currentOption.type === "scan_select") {
    return getSelectNestedOptions(currentOption)
  }

  if (currentOption.type === "checkbox") {
    return getCheckboxNestedOptions(currentOption)
  }

  return []
})
</script>
