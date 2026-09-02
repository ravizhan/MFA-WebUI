<template>
  <NSwitch size="small" :value="value === checkedValue" @update:value="handleValueChange" />
</template>

<script setup lang="ts">
import { computed } from "vue"
import type { SwitchOption } from "@/types/interfaceModel"

const { option, value } = defineProps<{
  option: SwitchOption
  value: string
}>()

const emit = defineEmits<{
  (event: "update:value", value: string): void
}>()

const checkedValue = computed(() =>
  ["Yes", "yes", "Y", "y"].includes(option.cases[1].name)
    ? option.cases[1].name
    : option.cases[0].name,
)

const uncheckedValue = computed(() =>
  ["Yes", "yes", "Y", "y"].includes(option.cases[1].name)
    ? option.cases[0].name
    : option.cases[1].name,
)

function handleValueChange(value: string | number | boolean): void {
  const checked = value === true || value === 1 || value === "true" || value === "1"
  emit("update:value", checked ? checkedValue.value : uncheckedValue.value)
}
</script>
