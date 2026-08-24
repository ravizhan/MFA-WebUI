<template>
  <template v-if="option">
    <div
      class="flex items-center justify-between w-full gap-4 py-2 px-3 border-b border-base-300 last:border-b-0"
      :style="{ paddingLeft: (level || 0) * 20 + 12 + 'px' }"
    >
      <div class="min-w-0 flex-1 text-sm">{{ resolvedLabel }}</div>
      <div class="flex flex-1 justify-end">
        <template v-if="option.type === 'switch'">
          <input
            type="checkbox"
            class="toggle toggle-primary toggle-sm"
            :true-value="checkedValue"
            :false-value="uncheckedValue"
            :checked="taskOptions[name] === checkedValue"
            @change="handleSwitchChange($event)"
          />
        </template>

        <template v-else-if="option.type === 'select'">
          <select
            v-model="taskOptions[name]"
            class="select select-bordered select-sm w-full max-w-xs"
          >
            <option v-for="opt in selectOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </template>

        <template v-else-if="option.type === 'scan_select'">
          <div class="flex w-full max-w-xs items-center gap-2">
            <select v-model="taskOptions[name]" class="select select-bordered select-sm flex-1">
              <option v-for="opt in selectOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
            <button
              class="btn btn-ghost btn-circle btn-sm"
              :disabled="scanSelectRefreshing"
              @click="handleRescanScanSelect"
            >
              <Icon
                icon="mdi:refresh"
                class="text-base"
                :class="{ 'animate-spin': scanSelectRefreshing }"
              />
            </button>
          </div>
        </template>

        <template v-else-if="option.type === 'input'">
          <div class="flex w-full max-w-sm flex-col gap-2">
            <div v-for="input in option.inputs" :key="input.name" class="flex flex-col gap-1">
              <span class="text-xs opacity-60">{{
                resolveInputLabel(input.label, input.name)
              }}</span>
              <input
                type="text"
                class="input input-bordered input-sm"
                :class="{ 'input-error': isInputError(input.name, input.verify) }"
                :value="getInputValue(input.name)"
                @input="
                  handleInputChange(
                    input.name,
                    getInputEventValue($event),
                    input,
                    $event.target instanceof HTMLInputElement ? $event.target : null,
                  )
                "
              />
            </div>
          </div>
        </template>

        <template v-else-if="option.type === 'checkbox'">
          <div class="flex flex-wrap gap-3">
            <label
              v-for="checkbox in option.cases"
              :key="checkbox.name"
              class="flex items-center gap-1 cursor-pointer"
            >
              <input
                type="checkbox"
                class="checkbox checkbox-primary checkbox-sm"
                :value="checkbox.name"
                :checked="checkboxValue.includes(checkbox.name)"
                @change="toggleCheckbox(checkbox.name, getChecked($event))"
              />
              <span class="text-sm">{{ resolveCaseLabel(checkbox.label, checkbox.name) }}</span>
            </label>
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
import { Icon } from "@iconify/vue"
import { showGlobalMessage } from "@/services/feedback/message"
import { useInterfaceStore } from "@/stores"
import type { InputCase } from "@/types/interfaceModel"
import type { NullableTaskOptionValue } from "@/types/schedulerModel"
import { makeInterfaceInputSchema } from "@/schemas/interfaceInput"
import { resolveInterfaceText } from "@/utils/interface/content"
import { tryCatch } from "@/utils/tryCatch"

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

function handleInputChange(
  inputName: string,
  value: string,
  input: InputCase,
  target: HTMLInputElement | null,
): void {
  const allowed = isInputAllowed(value, input.verify)
  const wasInvalid = inputInvalidState.value[inputName] === true

  if (allowed) {
    setInputValue(inputName, value)
    inputInvalidState.value = { ...inputInvalidState.value, [inputName]: false }
    return
  }

  // Invalid: do not update model; snap DOM back to previous value
  if (target) {
    target.value = getInputValue(inputName)
  }
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

function toggleCheckbox(checkboxName: string, checked: boolean) {
  const current = new Set(checkboxValue.value)
  if (checked) {
    current.add(checkboxName)
    checkboxValue.value = Array.from(current)
    return
  }
  current.delete(checkboxName)
  checkboxValue.value = Array.from(current)
}

function handleSwitchChange(event: Event) {
  taskOptions.value[name] = getChecked(event) ? checkedValue.value : uncheckedValue.value
}

function getInputEventValue(event: Event): string {
  const target = event.target
  if (target instanceof HTMLInputElement) return target.value
  return ""
}

function getChecked(event: Event): boolean {
  const target = event.target
  if (target instanceof HTMLInputElement) return target.checked
  return false
}

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
