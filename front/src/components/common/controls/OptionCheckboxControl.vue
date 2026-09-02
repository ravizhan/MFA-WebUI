<template>
  <div class="flex flex-wrap gap-3">
    <NCheckbox
      v-for="checkbox in option.cases"
      :key="checkbox.name"
      :checked="normalizedValue.includes(checkbox.name)"
      @update:checked="handleCheckboxChange(checkbox.name, $event)"
    >
      {{ resolveCaseLabel(checkbox.label, checkbox.name) }}
    </NCheckbox>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import { useI18n } from "vue-i18n"
import { useInterfaceStore } from "@/stores"
import type { CheckboxOption } from "@/types/interfaceModel"
import { resolveInterfaceText } from "@/utils/interface/content"

const { option, value } = defineProps<{
  option: CheckboxOption
  value: string[]
}>()

const emit = defineEmits<{
  (event: "update:value", value: string[]): void
}>()

const { locale } = useI18n()
const interfaceStore = useInterfaceStore()

const normalizedValue = computed(() => {
  const selected = new Set(value)
  return option.cases.map((item) => item.name).filter((name) => selected.has(name))
})

function resolveCaseLabel(label: string | undefined, fallback: string): string {
  return resolveInterfaceText(interfaceStore.interface, locale.value, label, fallback)
}

function handleCheckboxChange(checkboxName: string, checked: boolean): void {
  const selected = new Set(normalizedValue.value)
  if (checked) {
    selected.add(checkboxName)
  }
  if (!checked) {
    selected.delete(checkboxName)
  }
  emit(
    "update:value",
    option.cases.map((item) => item.name).filter((name) => selected.has(name)),
  )
}
</script>
