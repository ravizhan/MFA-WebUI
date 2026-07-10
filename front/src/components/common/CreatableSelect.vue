<template>
  <div class="dropdown w-full" :class="{ 'dropdown-open': isOpen }">
    <input
      type="text"
      role="combobox"
      aria-haspopup="listbox"
      :aria-expanded="isOpen"
      :aria-controls="isOpen ? listboxId : undefined"
      :value="displayValue"
      class="select select-sm w-full"
      :placeholder="placeholder"
      :disabled="disabled"
      @focus="handleFocus"
      @blur="handleBlur"
      @click="handleClick"
      @input="handleInput"
    />
    <ul
      v-if="isOpen"
      :id="listboxId"
      role="listbox"
      class="dropdown-content menu menu-sm bg-base-100 rounded-md shadow w-full max-h-60 overflow-y-auto mt-1 p-2 z-[999]"
    >
      <li
        v-if="visibleOptions.length === 0"
        class="menu-disabled"
        role="option"
        aria-disabled="true"
      >
        <a>{{ t("panel.noDevice") }}</a>
      </li>
      <li
        v-for="opt in visibleOptions"
        :key="opt.isCreate ? '__create__' : opt.value"
        role="option"
        :aria-selected="modelValue === opt.value"
        :class="{ 'menu-disabled': opt.disabled }"
        @mousedown.prevent="selectOption(opt)"
      >
        <a :aria-disabled="opt.disabled || undefined">
          <template v-if="opt.isCreate">
            <Icon icon="mdi:plus" class="text-xs opacity-60 shrink-0" />
            <span class="truncate">{{ t("panel.useCustomValue", { value: opt.label }) }}</span>
          </template>
          <template v-else>{{ opt.label }}</template>
        </a>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, useId, watch } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"

interface Option {
  label: string
  value: string
  isCreate?: boolean
  disabled?: boolean
}

const { options, placeholder, disabled } = defineProps<{
  options: Option[]
  placeholder?: string
  disabled?: boolean
}>()

const modelValue = defineModel<string | null>()

const emit = defineEmits<{
  (e: "open"): void
  (e: "create", value: string): void
}>()

const { t } = useI18n()
const isOpen = ref(false)
const inputText = ref("")
const listboxId = useId()

// Text shown in the input. While the user is typing (inputText non-empty),
// show what they're typing so it can be turned into a new option. Otherwise
// show the friendly label of the bound value, or the raw value, or empty.
const displayValue = computed(() => {
  if (inputText.value) return inputText.value
  const opt = options.find((o) => o.value === modelValue.value)
  return opt?.label || modelValue.value || ""
})

// The creatable option: any non-empty typed text that does not exactly match an
// existing option becomes a selectable entry, letting users input custom values
// (e.g. a manually-entered device address). Backend options are read-only —
// users can only select them as-is or create a brand-new value.
const createOption = computed<Option | null>(() => {
  const text = inputText.value.trim()
  if (!text) return null
  const lower = text.toLowerCase()
  const exists = options.some(
    (opt) => opt.label.toLowerCase() === lower || opt.value.toLowerCase() === lower,
  )
  if (exists) return null
  return { label: text, value: text, isCreate: true }
})

// No filtering: all backend options are always shown, plus the creatable
// option (if any) at the top.
const visibleOptions = computed(() => {
  const result = [...options]
  if (createOption.value) result.unshift(createOption.value)
  return result
})

watch(
  () => modelValue.value,
  () => {
    inputText.value = ""
  },
)

function handleFocus() {
  if (disabled) return
  const wasClosed = !isOpen.value
  isOpen.value = true
  if (wasClosed) emit("open")
}

function handleClick() {
  if (disabled) return
  const wasClosed = !isOpen.value
  isOpen.value = true
  if (wasClosed) emit("open")
}

function handleBlur() {
  // Close without committing — a new value is only committed by explicitly
  // clicking the creatable option. This prevents a half-typed value from
  // corrupting the bound value on accidental blur.
  setTimeout(() => {
    isOpen.value = false
    inputText.value = ""
  }, 200)
}

function getInputValue(event: Event): string {
  const target = event.target
  if (target instanceof HTMLInputElement) return target.value
  return ""
}

function handleInput(event: Event) {
  // Only update local text — do NOT emit update:modelValue. The bound value is
  // only emitted when an option (existing or creatable) is explicitly selected.
  inputText.value = getInputValue(event)
  const wasClosed = !isOpen.value
  isOpen.value = true
  if (wasClosed) emit("open")
}

function selectOption(opt: Option) {
  if (opt.disabled) return
  inputText.value = ""
  isOpen.value = false
  if (opt.isCreate) {
    emit("create", opt.value.trim())
    return
  }
  modelValue.value = opt.value
}
</script>
