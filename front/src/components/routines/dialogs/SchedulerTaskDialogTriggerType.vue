<template>
  <div class="space-y-1.5">
    <label class="flex items-center gap-1.5 text-sm font-medium">
      <NIcon size="16" class="opacity-70"><FlashOutline /></NIcon>
      {{ t("settings.scheduler.dialog.triggerType") }}
    </label>
    <NRadioGroup
      :value="triggerType"
      class="flex flex-wrap gap-2"
      @update:value="handleTriggerTypeChange"
    >
      <NRadioButton v-for="option in triggerOptions" :key="option.value" :value="option.value">
        <span class="flex items-center gap-2 text-sm">
          <NIcon size="16" class="opacity-70"><component :is="option.icon" /></NIcon>
          <span>{{ option.label }}</span>
        </span>
      </NRadioButton>
    </NRadioGroup>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n"
import { FlashOutline } from "@vicons/ionicons5"
import type { Component } from "vue"
import type { TriggerType } from "@/types/schedulerModel"

interface TriggerOption {
  value: TriggerType
  label: string
  icon: Component
}

const { triggerType, triggerOptions } = defineProps<{
  triggerType: TriggerType
  triggerOptions: TriggerOption[]
}>()

const emit = defineEmits<{
  (e: "update:trigger-type", value: string | number): void
}>()

const { t } = useI18n()

function handleTriggerTypeChange(value: string | number) {
  emit("update:trigger-type", value)
}
</script>
