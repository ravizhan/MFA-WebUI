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
            @change="
              taskOptions[name] = ($event.target as HTMLInputElement).checked
                ? checkedValue
                : uncheckedValue
            "
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
                :value="getInputValue(input.name)"
                @input="setInputValue(input.name, ($event.target as HTMLInputElement).value)"
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
                @change="toggleCheckbox(checkbox.name, ($event.target as HTMLInputElement).checked)"
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
import type { NullableTaskOptionValue, TaskOptionValue } from "@/types/scheduler/model"
import { resolveInterfaceText } from "@/utils/interface/content"

const props = defineProps<{
  name: string
  level?: number
  taskOptions: Record<string, NullableTaskOptionValue>
}>()
// sync setup
const { locale } = useI18n()
const interfaceStore = useInterfaceStore()
const taskOptions = computed(() => props.taskOptions)

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

function getInputValue(inputName: string): string {
  const currentValue = taskOptions.value[props.name]
  if (currentValue && typeof currentValue === "object" && !Array.isArray(currentValue)) {
    const inputValue = currentValue[inputName]
    return typeof inputValue === "string" ? inputValue : ""
  }
  return ""
}

function setInputValue(inputName: string, value: string): void {
  const currentValue = taskOptions.value[props.name]
  const nextValue: Record<string, string> =
    currentValue && typeof currentValue === "object" && !Array.isArray(currentValue)
      ? { ...currentValue }
      : {}

  nextValue[inputName] = value
  taskOptions.value[props.name] = nextValue
}

async function handleRescanScanSelect() {
  const currentOption = option.value
  if (!currentOption || currentOption.type !== "scan_select") {
    return
  }

  const previousValue = taskOptions.value[props.name]
  scanSelectRefreshing.value = true
  try {
    taskOptions.value[props.name] = null
    await interfaceStore.rescanScanSelectOption(props.name)
  } catch (error) {
    taskOptions.value[props.name] = previousValue
    if (error instanceof Error && error.message) {
      showGlobalMessage("error", error.message)
    }
  } finally {
    scanSelectRefreshing.value = false
  }
}

function normalizeCheckboxValue(
  value: NullableTaskOptionValue | undefined,
  caseOrder: string[],
): string[] {
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
      taskOptions.value[props.name],
      currentOption.cases.map((item) => item.name),
    )
  },
  set(value) {
    const currentOption = option.value
    if (!currentOption || currentOption.type !== "checkbox") {
      return
    }

    taskOptions.value[props.name] = normalizeCheckboxValue(
      value,
      currentOption.cases.map((item) => item.name),
    )
  },
})

function toggleCheckbox(name: string, checked: boolean) {
  const current = new Set(checkboxValue.value)
  if (checked) {
    current.add(name)
  } else {
    current.delete(name)
  }
  checkboxValue.value = Array.from(current)
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

  const currentValue = taskOptions.value[props.name]
  if (currentValue == null || typeof currentValue !== "string") {
    return false
  }

  return !selectOptions.value.some((item) => item.value === currentValue)
})

watch(
  () => isSelectValueInvalid.value,
  (invalid) => {
    if (invalid) {
      taskOptions.value[props.name] = null
    }
  },
  { immediate: true },
)

const nestedOptions = computed(() => {
  const currentOption = option.value
  if (!currentOption) return []
  const currentValue = taskOptions.value[props.name]

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
        taskOptions.value[props.name],
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
</script>
