<template>
  <div class="dropdown w-full" :class="{ 'dropdown-open': isOpen }">
    <div class="relative">
      <input
        ref="inputRef"
        type="text"
        :value="displayValue"
        class="input input-bordered input-sm w-full pr-8"
        :placeholder="placeholder"
        :disabled="disabled"
        @focus="handleFocus"
        @blur="handleBlur"
        @input="handleInput"
        @keydown.down.prevent="highlightNext"
        @keydown.up.prevent="highlightPrev"
        @keydown.enter.prevent="selectHighlighted"
        @keydown.esc="isOpen = false"
      />
      <button
        class="absolute right-1 top-1/2 -translate-y-1/2 btn btn-ghost btn-circle btn-xs"
        :disabled="disabled"
        @click.stop="toggleDropdown"
      >
        <Icon
          icon="mdi:chevron-down"
          class="transition-transform"
          :class="isOpen ? 'rotate-180' : ''"
        />
      </button>
    </div>
    <ul
      v-if="isOpen && filteredOptions.length > 0"
      class="dropdown-content menu menu-sm bg-base-100 rounded-box shadow-lg z-50 w-full max-h-60 overflow-y-auto mt-1 p-1"
    >
      <li
        v-for="(opt, index) in filteredOptions"
        :key="opt.value"
        :class="{ 'bg-base-200': highlightedIndex === index }"
        @mousedown.prevent="selectOption(opt)"
        @mouseenter="highlightedIndex = index"
      >
        <a class="text-sm">{{ opt.label }}</a>
      </li>
    </ul>
    <div
      v-else-if="isOpen && searchText && filteredOptions.length === 0"
      class="dropdown-content bg-base-100 rounded-box shadow-lg z-50 w-full mt-1 p-2 text-center text-sm opacity-50"
    >
      {{ t("panel.noMatchingDevice") }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from "vue"
import { useI18n } from "vue-i18n"
import { Icon } from "@iconify/vue"

interface Option {
  label: string
  value: string
}

const { options, placeholder, disabled } = defineProps<{
  options: Option[]
  placeholder?: string
  disabled?: boolean
}>()

const modelValue = defineModel<string | null>()

const { t } = useI18n()
const isOpen = ref(false)
const searchText = ref("")
const highlightedIndex = ref(-1)
const inputRef = useTemplateRef<HTMLInputElement>("inputRef")

const displayValue = computed(() => {
  if (searchText.value) return searchText.value
  const opt = options.find((o) => o.value === modelValue.value)
  return opt?.label || modelValue.value || ""
})

const filteredOptions = computed(() => {
  const text = searchText.value.toLowerCase()
  if (!text) return options
  return options.filter(
    (opt) => opt.label.toLowerCase().includes(text) || opt.value.toLowerCase().includes(text),
  )
})

watch(
  () => modelValue.value,
  () => {
    searchText.value = ""
  },
  { immediate: true },
)

function handleFocus() {
  isOpen.value = true
  searchText.value = displayValue.value
  highlightedIndex.value = -1
}

function handleBlur() {
  setTimeout(() => {
    isOpen.value = false
    searchText.value = ""
  }, 200)
}

function getInputValue(event: Event): string {
  const target = event.target
  if (target instanceof HTMLInputElement) return target.value
  return ""
}

function handleInput(event: Event) {
  // Only update the local filter text — do NOT emit update:modelValue.
  // Emitting raw filter text would corrupt the bound value (e.g. a device
  // fingerprint) with a partial label that no option matches. The real
  // value is only emitted when an option is explicitly selected.
  searchText.value = getInputValue(event)
  isOpen.value = true
  highlightedIndex.value = -1
}

function toggleDropdown() {
  if (disabled) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    nextTick(() => inputRef.value?.focus())
  }
}

function selectOption(opt: Option) {
  searchText.value = ""
  modelValue.value = opt.value
  isOpen.value = false
}

function highlightNext() {
  if (filteredOptions.value.length === 0) return
  highlightedIndex.value = (highlightedIndex.value + 1) % filteredOptions.value.length
}

function highlightPrev() {
  if (filteredOptions.value.length === 0) return
  highlightedIndex.value =
    (highlightedIndex.value - 1 + filteredOptions.value.length) % filteredOptions.value.length
}

function selectHighlighted() {
  if (highlightedIndex.value >= 0 && highlightedIndex.value < filteredOptions.value.length) {
    selectOption(filteredOptions.value[highlightedIndex.value])
    return
  }
  isOpen.value = false
}
</script>
